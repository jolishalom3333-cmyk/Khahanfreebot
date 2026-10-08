import os
import requests
from urllib.parse import quote
from flask import Flask, request

# --- 1. CẤU HÌNH BIẾN MÔI TRƯỜNG ---
ADMIN_ID = os.environ.get('ADMIN_ID') or "8860640969"
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()

# Thông tin cấu hình Facebook Messenger API
PAGE_ACCESS_TOKEN = os.environ.get('PAGE_ACCESS_TOKEN', '') # Lấy từ Meta for Developers
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN', 'nhungothilien_token')

app = Flask(__name__)

# Kết nối CSDL Supabase an toàn & Lưu lỗi chi tiết
supabase_error = ""
supabase = None

if not SUPABASE_URL:
    supabase_error = "Thiếu SUPABASE_URL trên Render Environment"
elif not SUPABASE_KEY:
    supabase_error = "Thiếu SUPABASE_KEY trên Render Environment"
else:
    try:
        from supabase import create_client
        clean_url = SUPABASE_URL.strip("[]'\" ")
        clean_key = SUPABASE_KEY.strip("[]'\" ")
        supabase = create_client(clean_url, clean_key)
        print("✅ Kết nối Supabase thành công!")
    except Exception as e:
        supabase_error = f"Lỗi khởi tạo Supabase: {str(e)}"
        print(f"❌ {supabase_error}")

# --- HÀM GỬI TIN NHẮN QUA FACEBOOK MESSENGER ---
def send_fb_message(recipient_id, text_message):
    if not PAGE_ACCESS_TOKEN:
        print("⚠️ Chưa có PAGE_ACCESS_TOKEN để gửi tin nhắn Facebook.")
        return
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text_message}
    }
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print("Lỗi gửi tin nhắn Facebook:", e)

# --- 2. HÀM ĐỌC / GHI DỮ LIỆU TỪ SUPABASE ---
def get_user(user_id):
    if not supabase:
        return None
    try:
        res = supabase.table('users').select('*').eq('id', str(user_id)).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print("Lỗi đọc dữ liệu Supabase:", e)
    return None

def save_or_update_user(user_id, name=None, username=None, balance=None, orders=None):
    if not supabase:
        return
    try:
        user_id_str = str(user_id)
        existing = get_user(user_id_str)
        
        if existing:
            data_to_update = {}
            if name is not None: data_to_update["name"] = name
            if username is not None: data_to_update["username"] = username
            if balance is not None: data_to_update["balance"] = balance
            if orders is not None: data_to_update["orders"] = orders
            
            if data_to_update:
                supabase.table('users').update(data_to_update).eq('id', user_id_str).execute()
        else:
            new_data = {
                "id": user_id_str,
                "name": name or "Khách hàng",
                "username": username or "",
                "balance": balance if balance is not None else 0,
                "orders": orders if orders is not None else []
            }
            supabase.table('users').insert(new_data).execute()
    except Exception as e:
        print("Lỗi ghi dữ liệu Supabase:", e)


# --- 3. WEBHOOK TỔNG HỢP: NHẬN TIN NHẮN FACEBOOK & POSTBACK ADPIA ---
@app.route('/', methods=['GET', 'POST', 'HEAD'])
def main_webhook():
    if request.method == 'HEAD':
        return "", 200

    # A. XỬ LÝ XÁC THỰC GET TỪ FACEBOOK MESSENGER
    if request.method == 'GET':
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        elif mode or token or 'hub.challenge' in request.args:
            return "Verification failed", 403
        
        return "Hệ thống Webhook Facebook & Adpia đang hoạt động ổn định!", 200

    # B. XỬ LÝ POST (NHẬN TIN NHẮN TỪ FACEBOOK HOẶC POSTBACK TỪ ADPIA)
    if request.method == 'POST':
        # 1. Xử lý dữ liệu gửi từ Facebook Messenger
        if request.is_json:
            data = request.json
            if data and data.get("object") == "page":
                try:
                    for entry in data.get("entry", []):
                        for messaging in entry.get("messaging", []):
                            sender_id = messaging.get("sender", {}).get("id")
                            message = messaging.get("message", {})
                            message_text = message.get("text")
                            
                            if message_text:
                                text_lower = message_text.strip().lower()
                                
                                # Khởi tạo hoặc cập nhật user khi họ nhắn tin lần đầu
                                user = get_user(sender_id)
                                if not user:
                                    save_or_update_user(sender_id, name="Khách hàng FB", balance=0, orders=[])
                                
                                # Phản hồi nút/lệnh "Đơn hàng của tôi"
                                if "đơn hàng" in text_lower:
                                    current_user = get_user(sender_id)
                                    orders = current_user.get("orders", []) if current_user else []
                                    if not orders:
                                        send_fb_message(sender_id, "📦 Bạn chưa có đơn hàng nào được ghi nhận.")
                                    else:
                                        recent = orders[-10:]
                                        msg_text = "📦 LỊCH SỬ ĐƠN HÀNG:\n\n" + "\n".join([f"• {item}" for item in recent])
                                        send_fb_message(sender_id, msg_text)
                                        
                                # Phản hồi nút/lệnh "Ví & Số dư"
                                elif "ví" in text_lower or "số dư" in text_lower:
                                    current_user = get_user(sender_id)
                                    bal = current_user.get("balance", 0) if current_user else 0
                                    send_fb_message(sender_id, f"💳 Số dư tích lũy của bạn: {bal:,.0f} VNĐ")
                                    
                                # Xử lý khi khách gửi link Shopee / TikTok
                                elif text_lower.startswith("http"):
                                    raw_url = message_text.strip()
                                    encoded_url = quote(raw_url, safe='')
                                    
                                    if "tiktok" in raw_url.lower():
                                        merchant = "tiktoksharelink"
                                    else:
                                        merchant = "shopee"

                                    link_adpia = f"https://click.adpia.vn/tracking.php?m={merchant}&a=A100156876&l=9999&tu={encoded_url}&utm_source={sender_id}"
                                    reply_content = (
                                        f"🛍️ LINK MUA HÀNG HOÀN TIỀN\n\n"
                                        f"Bấm vào liên kết sau để tiến hành mua sắm và nhận thưởng tự động:\n{link_adpia}"
                                    )
                                    send_fb_message(sender_id, reply_content)
                                    
                                else:
                                    # Tin nhắn mặc định chào mừng
                                    send_fb_message(
                                        sender_id, 
                                        "👋 Chào mừng bạn đến với hệ thống hoàn tiền! Hãy gửi link sản phẩm Shopee hoặc TikTok vào đây để nhận link mua hàng tích lũy."
                                    )
                except Exception as e:
                    print(f"Lỗi xử lý Facebook Webhook: {e}")
                return "EVENT_RECEIVED", 200

        # 2. Xử lý Postback từ Adpia (Cộng / Trừ tiền vào Supabase)
        target_id = request.args.get('sub_id') or request.args.get('subid') or request.args.get('utm_source')
        comm_str = request.args.get('commission') or request.args.get('comm') or request.args.get('money')
        status = request.args.get('status') or request.args.get('state') or 'success'
        order_id = request.args.get('order_id') or request.args.get('order_code') or 'Mới'

        if target_id and comm_str:
            try:
                target_id = str(target_id).strip()
                total_comm = float(comm_str)
                cashback = int(total_comm * 0.90)
                admin_profit = int(total_comm - cashback)
                status_clean = str(status).lower().strip()

                user = get_user(target_id)
                old_bal = user.get("balance", 0) if user else 0
                old_orders = user.get("orders", []) if user else []

                # XỬ LÝ ĐƠN HỦY / TRẢ HÀNG (TRỪ TIỀN)
                if status_clean in ["cancel", "cancelled", "0", "reject", "rejected"]:
                    new_bal = max(0, old_bal - cashback)
                    old_orders.append(f"❌ Hủy đơn #{order_id}: -{cashback:,.0f} VNĐ")
                    save_or_update_user(target_id, balance=new_bal, orders=old_orders)

                    send_fb_message(
                        target_id,
                        f"⚠️ CẬP NHẬT: ĐƠN HÀNG BỊ HỦY / TRẢ HÀNG!\n\n"
                        f"📦 Mã đơn: {order_id}\n"
                        f"🔻 Khấu trừ: -{cashback:,.0f} VNĐ khỏi ví tích lũy."
                    )

                    if ADMIN_ID:
                        send_fb_message(
                            ADMIN_ID,
                            f"🔻 BÁO CÓ ĐƠN HÀNG BỊ HỦY!\n"
                            f"🆔 ID Khách: {target_id}\n"
                            f"📦 Mã đơn: {order_id}\n"
                            f"🔻 Trừ hoàn khách (90%): -{cashback:,.0f} VNĐ"
                        )

                # XỬ LÝ ĐƠN MỚI THÀNH CÔNG (CỘNG TIỀN)
                else:
                    new_bal = old_bal + cashback
                    old_orders.append(f"🛒 Hoàn tiền đơn #{order_id}: +{cashback:,.0f} VNĐ")
                    save_or_update_user(target_id, balance=new_bal, orders=old_orders)

                    send_fb_message(
                        target_id, 
                        f"🎉 ĐƠN HÀNG MỚI ĐƯỢC GHI NHẬN!\n\n"
                        f"📦 Mã đơn: {order_id}\n"
                        f"💰 Bạn được cộng +{cashback:,.0f} VNĐ (90% hoa hồng) vào ví tích lũy!"
                    )

                    if ADMIN_ID:
                        send_fb_message(
                            ADMIN_ID,
                            f"🔔 CÓ ĐƠN HÀNG MỚI TỪ KHÁCH!\n"
                            f"🆔 ID Khách: {target_id}\n"
                            f"📦 Mã đơn: {order_id}\n"
                            f"🎁 Hoàn khách (90%): +{cashback:,.0f} VNĐ\n"
                            f"💵 Lợi nhuận Admin (10%): +{admin_profit:,.0f} VNĐ"
                        )

            except Exception as e:
                print(f"Lỗi xử lý Postback Adpia: {e}")

    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
