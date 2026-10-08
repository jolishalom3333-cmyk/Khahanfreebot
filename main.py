import os
import requests
from urllib.parse import quote
from flask import Flask, request

# --- 1. CẤU HÌNH BIẾN MÔI TRƯỜNG ---
ADMIN_ID = os.environ.get('ADMIN_ID') or "8860640969"
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()

PAGE_ACCESS_TOKEN = os.environ.get('PAGE_ACCESS_TOKEN', '')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN', 'nhungothilien_token')

app = Flask(__name__)

supabase_error = ""
supabase = None

if not SUPABASE_URL or not SUPABASE_KEY:
    supabase_error = "Thiếu Supabase URL hoặc Key"
else:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL.strip("[]'\" "), SUPABASE_KEY.strip("[]'\" "))
        print("✅ Kết nối Supabase thành công!")
    except Exception as e:
        print(f"❌ Lỗi khởi tạo Supabase: {str(e)}")

def send_fb_message(recipient_id, text_message):
    if not PAGE_ACCESS_TOKEN:
        print("⚠️ Chưa có PAGE_ACCESS_TOKEN.")
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

def get_user(user_id):
    if not supabase:
        return None
    try:
        res = supabase.table('users').select('*').eq('id', str(user_id)).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print("Lỗi đọc Supabase:", e)
    return None

def save_or_update_user(user_id, name=None, balance=None, orders=None):
    if not supabase:
        return
    try:
        user_id_str = str(user_id)
        existing = get_user(user_id_str)
        if existing:
            data_to_update = {}
            if name is not None: data_to_update["name"] = name
            if balance is not None: data_to_update["balance"] = balance
            if orders is not None: data_to_update["orders"] = orders
            if data_to_update:
                supabase.table('users').update(data_to_update).eq('id', user_id_str).execute()
        else:
            new_data = {
                "id": user_id_str,
                "name": name or "Khách hàng",
                "username": "",
                "balance": balance if balance is not None else 0,
                "orders": orders if orders is not None else []
            }
            supabase.table('users').insert(new_data).execute()
    except Exception as e:
        print("Lỗi ghi Supabase:", e)

# --- HÀM XỬ LÝ LOGIC CHUNG CHO CẢ 2 ROUTE '/' VÀ '/webhook' ---
def handle_webhook_logic():
    if request.method == 'HEAD':
        return "", 200

    # 1. XỬ LÝ XÁC THỰC GET TỪ FACEBOOK
    if request.method == 'GET':
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        elif mode or token or 'hub.challenge' in request.args:
            return "Verification failed", 403
        
        return "Bot hoàn tiền đang hoạt động!", 200

    # 2. XỬ LÝ POST (NHẬN TIN NHẮN TỪ FB HOẶC POSTBACK ADPIA)
    if request.method == 'POST':
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
                                user = get_user(sender_id)
                                if not user:
                                    save_or_update_user(sender_id, name="Khách hàng FB", balance=0, orders=[])
                                
                                if "đơn hàng" in text_lower:
                                    current_user = get_user(sender_id)
                                    orders = current_user.get("orders", []) if current_user else []
                                    if not orders:
                                        send_fb_message(sender_id, "📦 Bạn chưa có đơn hàng nào được ghi nhận.")
                                    else:
                                        recent = orders[-10:]
                                        send_fb_message(sender_id, "📦 LỊCH SỬ ĐƠN HÀNG:\n\n" + "\n".join([f"• {item}" for item in recent]))
                                        
                                elif "ví" in text_lower or "số dư" in text_lower:
                                    current_user = get_user(sender_id)
                                    bal = current_user.get("balance", 0) if current_user else 0
                                    send_fb_message(sender_id, f"💳 Số dư tích lũy của bạn: {bal:,.0f} VNĐ")
                                    
                                elif text_lower.startswith("http"):
                                    raw_url = message_text.strip()
                                    encoded_url = quote(raw_url, safe='')
                                    merchant = "tiktoksharelink" if "tiktok" in raw_url.lower() else "shopee"
                                    link_adpia = f"https://click.adpia.vn/tracking.php?m={merchant}&a=A100156876&l=9999&tu={encoded_url}&utm_source={sender_id}"
                                    send_fb_message(sender_id, f"🛍️ LINK MUA HÀNG HOÀN TIỀN:\n\n{link_adpia}")
                                    
                                else:
                                    send_fb_message(sender_id, "👋 Chào mừng bạn! Hãy gửi link sản phẩm Shopee hoặc TikTok vào đây để nhận link mua hàng tích lũy.")
                except Exception as e:
                    print(f"Lỗi xử lý FB Webhook: {e}")
                return "EVENT_RECEIVED", 200

        # Xử lý Postback từ Adpia
        target_id = request.args.get('sub_id') or request.args.get('subid') or request.args.get('utm_source')
        comm_str = request.args.get('commission') or request.args.get('comm') or request.args.get('money')
        status = request.args.get('status') or request.args.get('state') or 'success'
        order_id = request.args.get('order_id') or request.args.get('order_code') or 'Mới'

        if target_id and comm_str:
            try:
                target_id = str(target_id).strip()
                cashback = int(float(comm_str) * 0.90)
                user = get_user(target_id)
                old_bal = user.get("balance", 0) if user else 0
                old_orders = user.get("orders", []) if user else []

                if str(status).lower().strip() in ["cancel", "cancelled", "0", "reject", "rejected"]:
                    new_bal = max(0, old_bal - cashback)
                    old_orders.append(f"❌ Hủy đơn #{order_id}: -{cashback:,.0f} VNĐ")
                    save_or_update_user(target_id, balance=new_bal, orders=old_orders)
                    send_fb_message(target_id, f"⚠️ Đơn hàng #{order_id} bị hủy. Trừ -{cashback:,.0f} VNĐ khỏi ví.")
                else:
                    new_bal = old_bal + cashback
                    old_orders.append(f"🛒 Hoàn tiền đơn #{order_id}: +{cashback:,.0f} VNĐ")
                    save_or_update_user(target_id, balance=new_bal, orders=old_orders)
                    send_fb_message(target_id, f"🎉 Đơn hàng #{order_id} thành công! Cộng +{cashback:,.0f} VNĐ vào ví.")
            except Exception as e:
                print(f"Lỗi Postback Adpia: {e}")

    return "OK", 200

@app.route('/', methods=['GET', 'POST', 'HEAD'])
def index():
    return handle_webhook_logic()

@app.route('/webhook', methods=['GET', 'POST', 'HEAD'])
def webhook():
    return handle_webhook_logic()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
                    
