import os
import requests
from urllib.parse import quote
from flask import Flask, request

ADMIN_ID = os.environ.get('ADMIN_ID') or "8860640969"
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()
PAGE_ACCESS_TOKEN = os.environ.get('PAGE_ACCESS_TOKEN', '')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN', 'ha_linh_123')

app = Flask(__name__)

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL.strip("[]'\" "), SUPABASE_KEY.strip("[]'\" "))
        print("✅ Kết nối Supabase thành công!")
    except Exception as e:
        print(f"❌ Lỗi khởi tạo Supabase: {str(e)}")

def send_fb_message(recipient_id, text_message):
    if not PAGE_ACCESS_TOKEN:
        return
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text_message}}
    try:
        requests.post(url, json=payload)
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
            supabase.table('users').insert({
                "id": user_id_str,
                "name": name or "Khách hàng",
                "username": "",
                "balance": balance if balance is not None else 0,
                "orders": orders if orders is not None else []
            }).execute()
    except Exception as e:
        print("Lỗi ghi Supabase:", e)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook_handler():
    if request.method == 'GET':
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Verification failed", 403

    if request.method == 'POST':
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
                            if not get_user(sender_id):
                                save_or_update_user(sender_id, name="Khách hàng FB", balance=0, orders=[])
                            
                            if text_lower.startswith("http"):
                                raw_url = message_text.strip()
                                merchant = "tiktoksharelink" if "tiktok" in raw_url.lower() else "shopee"
                                link_adpia = f"https://click.adpia.vn/tracking.php?m={merchant}&a=A100156876&l=9999&tu={quote(raw_url, safe='')}&utm_source={sender_id}"
                                send_fb_message(sender_id, f"🛍️ LINK MUA HÀNG HOÀN TIỀN:\n\n{link_adpia}")
                            else:
                                send_fb_message(sender_id, "👋 Gửi link sản phẩm Shopee hoặc TikTok vào đây để nhận link mua hàng tích lũy.")
            except Exception as e:
                print(f"Lỗi xử lý Webhook: {e}")
        return "EVENT_RECEIVED", 200

@app.route('/', methods=['GET'])
def index():
    return "Bot đang hoạt động!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
