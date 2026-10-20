import os
import json
import threading
import time
from datetime import datetime
from urllib.parse import quote
from flask import Flask, request
import requests
import telebot

# --- 1. CẤU HÌNH BIẾN MÔI TRƯỜNG ---
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID') or "8860640969"
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()

# Biến môi trường RioHub
RIOHUB_API_KEY = os.environ.get('RIOHUB_API_KEY', '').strip()

# Tỷ lệ hoàn tiền (Mặc định 90%)
CASHBACK_RATE = float(os.environ.get('CASHBACK_PERCENT', 90)) / 100.0

bot = telebot.TeleBot(TOKEN) if TOKEN else None
app = Flask(__name__)

# Kết nối CSDL Supabase
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL.strip("[]'\" "), SUPABASE_KEY.strip("[]'\" "))
        print("✅ Kết nối Supabase thành công!")
    except Exception as e:
        print(f"❌ Lỗi Supabase: {e}")

def get_user(user_id):
    if not supabase: return None
    try:
        res = supabase.table('users').select('*').eq('id', str(user_id)).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print("Lỗi get_user:", e)
        return None

def save_or_update_user(user_id, name=None, username=None, balance=None, orders=None):
    if not supabase: return
    try:
        uid = str(user_id)
        existing = get_user(uid)
        if existing:
            data = {}
            if name is not None: data["name"] = name
            if username is not None: data["username"] = username
            if balance is not None: data["balance"] = balance
            if orders is not None: data["orders"] = orders
            if data:
                supabase.table('users').update(data).eq('id', uid).execute()
        else:
            new_data = {
                "id": uid,
                "name": name or "Khách hàng",
                "username": username or "",
                "balance": balance if balance is not None else 0,
                "orders": orders if orders is not None else []
            }
            supabase.table('users').insert(new_data).execute()
    except Exception as e:
        print("Lỗi save_user:", e)

def log_click(user_id, raw_url):
    if not supabase: return
    try:
        supabase.table('clicks').insert({
            "user_id": str(user_id),
            "original_url": raw_url,
            "created_at": datetime.now().isoformat()
        }).execute()
    except Exception as e:
        print("Lỗi log_click:", e)

def convert_link_riohub(original_url, user_id):
    if not RIOHUB_API_KEY: return None
    endpoint = "https://riohub.vn/api/v1/partner/tiktok/affiliate/links"
    headers = {"X-Riohub-Api-Key": RIOHUB_API_KEY, "Content-Type": "application/json"}
    payload = {"product_url": original_url, "sub_id": str(user_id)}
    try:
        res = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return data.get("affiliate_link") or data.get("link") or data.get("data", {}).get("affiliate_link")
    except Exception as e:
        print("Lỗi RioHub API:", e)
    return None

if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        uid = str(message.chat.id)
        first_name = message.from_user.first_name or "Khách"
        username = message.from_user.username or ""
        save_or_update_user(uid, name=first_name, username=username)

        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("📦 Đơn hàng của tôi", "💳 Ví & Số dư")
        markup.add("❓ Hướng dẫn mua hàng", "💬 Hỗ trợ Admin")
        
        welcome_text = (
            f"👋 **Chào mừng {first_name} đến với Bot Hoàn Tiền Tự Động!**\n\n"
            f"🛒 **Cách nhận hoàn tiền {int(CASHBACK_RATE * 100)}%:**\n"
            f"1️⃣ Copy link sản phẩm trên Shopee / TikTok Shop.\n"
            f"2️⃣ Gửi link trực tiếp vào đây cho Bot.\n"
            f"3️⃣ Bấm link rút gọn Bot trả về để mua hàng.\n\n"
            f"📌 *Bấm '❓ Hướng dẫn mua hàng' bên dưới để xem chi tiết!*"
        )
        bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text == "📦 Đơn hàng của tôi")
    def my_orders(message):
        user = get_user(message.from_user.id)
        orders = user.get("orders", []) if user else []
        if not orders:
            bot.reply_to(message, "📦 Bạn chưa có đơn hàng nào được ghi nhận.")
        else:
            msg_text = "📦 **LỊCH SỬ ĐƠN HÀNG GẦN ĐÂY:**\n\n" + "\n".join([f"• {item}" for item in orders[-10:]])
            bot.reply_to(message, msg_text, parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text == "💳 Ví & Số dư")
    def my_balance(message):
        user = get_user(message.from_user.id)
        bal = user.get("balance", 0) if user else 0
        bot.reply_to(message, f"💳 **SỐ DƯ VÍ TÍCH LŨY:** `{bal:,.0f} VNĐ`", parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text in ["❓ Hướng dẫn mua hàng", "/huongdan"])
    def guide(message):
        guide_text = (
            "📌 **QUY TRÌNH MUA HÀNG NHẬN HOÀN TIỀN:**\n\n"
            "1️⃣ Xóa sản phẩm khỏi giỏ trước khi gửi link.\n"
            "2️⃣ Gửi link vào Bot ➔ Bấm link Bot trả về ➔ Mua ngay.\n"
            "3️⃣ Đơn TikTok Shop cập nhật sau 1-3 giờ, Shopee sau 24h-48h."
        )
        bot.reply_to(message, guide_text, parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text == "💬 Hỗ trợ Admin")
    def admin_support(message):
        bot.reply_to(message, "💬 Hãy gửi nội dung cần hỗ trợ kèm mã đơn/SĐT vào đây nhé!")

    @bot.message_handler(func=lambda msg: msg.text is not None and msg.text.startswith("http"))
    def convert_link(message):
        uid = message.from_user.id
        raw_url = message.text.strip()
        log_click(uid, raw_url)
        
        if "tiktok" in raw_url.lower():
            afflink = convert_link_riohub(raw_url, uid)
            if not afflink:
                encoded_url = quote(raw_url, safe='')
                afflink = f"https://go.isclix.com/deep_link/7073909970291373175/6648523843406889655?url={encoded_url}&sub_id={uid}"
        else:
            encoded_url = quote(raw_url, safe='')
            afflink = f"https://go.isclix.com/deep_link/7073909970291373175/4751584435713464237?url={encoded_url}&sub4=oneatweb&sub_id={uid}"
        
        bot.reply_to(
            message, 
            f"🛍️ <a href='{afflink}'><b>LINK MUA HÀNG HOÀN TIỀN {int(CASHBACK_RATE*100)}%</b></a>\n\n"
            f"👉 <a href='{afflink}'>BẤM VÀO ĐÂY ĐỂ MUA HÀNG</a>", 
            parse_mode="HTML"
        )

@app.route('/', methods=['GET', 'POST', 'HEAD'])
@app.route('/postback', methods=['GET', 'POST', 'HEAD'])
def webhook():
    if request.method == 'HEAD':
        return "", 200

    if request.is_json or request.method == 'POST':
        try:
            body_bytes = request.get_data()
            data = json.loads(body_bytes.decode('utf-8')) if body_bytes else {}
            if data and ("order_id" in data or "commission" in data):
                target_id = str(data.get("sub_id") or "").strip()
                comm = float(data.get("commission") or 0)
                order_id = str(data.get("order_id") or "Mới")
                event_type = str(data.get("event") or "").lower()

                if target_id and comm > 0 and bot:
                    cashback = int(comm * CASHBACK_RATE)
                    user = get_user(target_id)
                    old_bal = user.get("balance", 0) if user else 0
                    old_orders = user.get("orders", []) if user else []

                    if event_type in ["order.refunded", "cancelled"]:
                        new_bal = max(0, old_bal - cashback)
                        old_orders.append(f"❌ Hủy đơn #{order_id}: -{cashback:,.0f} VNĐ")
                        save_or_update_user(target_id, balance=new_bal, orders=old_orders)
                    else:
                        new_bal = old_bal + cashback
                        old_orders.append(f"🛒 Hoàn tiền #{order_id}: +{cashback:,.0f} VNĐ")
                        save_or_update_user(target_id, balance=new_bal, orders=old_orders)
                        try:
                            bot.send_message(target_id, f"🎉 **ĐƠN HÀNG MỚI GHI NHẬN!**\n📦 Mã đơn: `{order_id}`\n💰 Cộng: +{cashback:,.0f} VNĐ", parse_mode="Markdown")
                        except Exception:
                            pass
                return "OK", 200
        except Exception as e:
            print("Lỗi Postback:", e)

    return "Server Bot Cashback đang chạy mượt mà!", 200

def run_bot():
    if not bot: return
    try:
        bot.remove_webhook()
    except Exception:
        pass
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception as e:
            time.sleep(5)

threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
        
