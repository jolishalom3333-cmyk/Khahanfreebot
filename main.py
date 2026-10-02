import os
import re
import time
import threading
from urllib.parse import quote
from flask import Flask, request, jsonify
import requests
import telebot

app = Flask(__name__)

# --- 1. CẤU HÌNH BIẾN MÔI TRƯỜNG ---
TOKEN = (os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN') or '8667094035:AAHUvKewgoz1jHUhYPRGoycpSx24gXB3X60').strip("[]'\" ")
ADMIN_ID = (os.environ.get('ADMIN_ID') or '8860640969').strip("[]'\" ")
SUPABASE_URL = (os.environ.get('SUPABASE_URL') or '').strip("[]'\" ")
SUPABASE_KEY = (os.environ.get('SUPABASE_KEY') or '').strip("[]'\" ")

# Cấu hình ACCESSTRADE API Key chính chủ của bạn
ACCESSTRADE_API_KEY = (os.environ.get('ACCESSTRADE_API_KEY') or 'mC9R_6IaprMxC1AO1GJfa37zL4QiRjzo').strip("[]'\" ")
DEEPLINK_API_URL = "https://api.accesstrade.vn/v1/deeplinks"

# --- KHỞI TẠO BOT & DATABASE ---
bot = telebot.TeleBot(TOKEN) if TOKEN else None

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Kết nối Supabase thành công!")
    except Exception as e:
        print(f"❌ Lỗi Supabase: {e}")

# --- KẾT NỐI DATABASE SUPABASE ---
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
            update_data = {}
            if name is not None: update_data["name"] = name
            if username is not None: update_data["username"] = username
            if balance is not None: update_data["balance"] = balance
            if orders is not None: update_data["orders"] = orders
            if update_data:
                supabase.table('users').update(update_data).eq('id', uid).execute()
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

# --- HÀM TẠO DEEPLINK BẰNG ACCESSTRADE API (DÙNG CHUNG CHO SHOPEE & TIKTOK) ---
def create_accesstrade_deeplink(clean_url, user_id):
    headers = {
        "Authorization": f"Token {ACCESSTRADE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "urls": [clean_url],
        "utm_source": str(user_id)  # Gắn ID khách hàng để nhận diện lúc postback trả về
    }
    try:
        res = requests.post(DEEPLINK_API_URL, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            if data.get("result") and len(data["result"]["success"]) > 0:
                return data["result"]["success"][0]["short_link"]
    except Exception as e:
        print("❌ Lỗi API ACCESSTRADE Deeplink:", e)
    return None

# --- SERVER FLASK ROUTE ---
@app.route('/', methods=['GET', 'HEAD', 'POST'])
def index():
    return "Bot ACCESSTRADE đang chạy bình thường!", 200

# --- LOGIC XỬ LÝ LỆNH BOT ---
if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        uid = str(message.chat.id)
        first_name = message.from_user.first_name or "Khách"
        username = message.from_user.username or ""
        user = get_user(uid)
        if not user:
            save_or_update_user(uid, name=first_name, username=username, balance=0, orders=[])
        else:
            save_or_update_user(uid, name=first_name, username=username)

        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("📦 Đơn hàng của tôi", "💳 Ví & Số dư")
        bot.reply_to(message, f"👋 Chào mừng {first_name}! Hãy gửi link Shopee hoặc TikTok Shop để mua hàng hoàn tiền **90%**.", parse_mode="Markdown", reply_markup=markup)

    @bot.message_handler(func=lambda msg: msg.text == "📦 Đơn hàng của tôi")
    def my_orders(message):
        uid = str(message.from_user.id)
        user = get_user(uid)
        orders = user.get("orders", []) if user else []
        if not orders:
            bot.reply_to(message, "📦 Bạn chưa có đơn hàng nào được ghi nhận.")
        else:
            recent = orders[-10:]
            msg_text = "📦 **LỊCH SỬ ĐƠN HÀNG:**\n\n" + "\n".join([f"• {item}" for item in recent])
            bot.reply_to(message, msg_text, parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text == "💳 Ví & Số dư")
    def my_balance(message):
        uid = str(message.from_user.id)
        user = get_user(uid)
        bal = user.get("balance", 0) if user else 0
        bot.reply_to(message, f"💳 **Số dư tích lũy của bạn:** {bal:,.0f} VNĐ", parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text is not None and "http" in msg.text)
    def convert_link(message):
        uid = message.from_user.id
        raw_text = message.text.strip()
        url_match = re.search(r'https?://[^\s]+', raw_text)
        clean_url = url_match.group(0) if url_match else raw_text

        if "tiktok" in clean_url.lower() or "shopee" in clean_url.lower() or "shp.ee" in clean_url.lower() or "vt.tiktok" in clean_url.lower():
            at_link = create_accesstrade_deeplink(clean_url, uid)
            platform_name = "TIKTOK SHOP" if "tiktok" in clean_url.lower() or "vt.tiktok" in clean_url.lower() else "SHOPEE"
            if at_link:
                bot.reply_to(message, f"🛒 <a href='{at_link}'><b>LINK {platform_name} HOÀN TIỀN 90%</b></a>\n\n👉 <a href='{at_link}'>BẤM VÀO ĐÂY ĐỂ MUA HÀNG</a>", parse_mode="HTML")
            else:
                bot.reply_to(message, f"❌ Tạo link {platform_name} thất bại. Vui lòng kiểm tra lại đường dẫn sản phẩm!")
        else:
            bot.reply_to(message, "⚠️️ Bot hiện hỗ trợ tạo link hoàn tiền cho **Shopee** và **TikTok Shop**.", parse_mode="Markdown")

    @bot.message_handler(commands=['congtien'])
    def cong_tien(message):
        if str(message.from_user.id) != str(ADMIN_ID): return
        try:
            parts = message.text.split()
            target_id = parts[1]
            amount = int(parts[2])
            user = get_user(target_id)
            old_bal = user.get("balance", 0) if user else 0
            old_orders = user.get("orders", []) if user else []
            new_bal = old_bal + amount
            old_orders.append(f"➕ Admin cộng tay: +{amount:,.0f} VNĐ")
            save_or_update_user(target_id, balance=new_bal, orders=old_orders)
            bot.reply_to(message, f"✅ Đã cộng {amount:,.0f} VNĐ cho ID {target_id}")
        except Exception:
            bot.reply_to(message, "⚠️ Cú pháp: `/congtien <USER_ID> <SO_TIEN>`", parse_mode="Markdown")

    @bot.message_handler(commands=['danhsach'])
    def list_users(message):
        if str(message.from_user.id) != str(ADMIN_ID): return
        try:
            if not supabase:
                bot.reply_to(message, "❌ Chưa kết nối Supabase.")
                return
            res = supabase.table('users').select('*').execute()
            users = res.data
            if not users:
                bot.reply_to(message, "📂 Chưa có khách hàng nào.")
                return
            msg = "📋 <b>DANH SÁCH KHÁCH HÀNG:</b>\n\n"
            for info in users:
                uid = info['id']
                name = info.get("name", "Khách hàng")
                balance = info.get("balance", 0)
                msg += f"👤 <b>{name}</b> (ID: <code>{uid}</code>) - Số dư: <b>{balance:,.0f} VNĐ</b>\n"
            bot.send_message(ADMIN_ID, msg, parse_mode="HTML")
        except Exception as e:
            bot.reply_to(message, f"❌ Lỗi: {e}")

    @bot.message_handler(commands=['nhan'])
    def send_custom_msg(message):
        if str(message.from_user.id) != str(ADMIN_ID): return
        try:
            p = message.text.split(" ", 2)
            bot.send_message(p[1], f"💬 **Lời nhắn từ Admin:**\n\n{p[2]}", parse_mode="Markdown")
            bot.reply_to(message, "✅ Đã gửi tin nhắn thành công!")
        except Exception:
            bot.reply_to(message, "⚠️ Cú pháp: `/nhan <ID_KHÁCH> <NỘI_DUNG>`", parse_mode="Markdown")

# --- POSTBACK ENDPOINT NHẬN ĐƠN TỪ ACCESSTRADE ---
@app.route('/postback', methods=['GET', 'POST'])
def postback_accesstrade():
    """Nhận postback chung từ ACCESSTRADE, tự động tính 90% cho khách, 10% cho bạn"""
    target_id = request.args.get('utm_source') or request.args.get('sub_id')
    comm_str = request.args.get('pub_commission') or request.args.get('commission')
    status = request.args.get('status') or '1'
    order_id = request.args.get('order_id') or 'Mới'

    if target_id and comm_str and bot:
        try:
            target_id = str(target_id).strip()
            total_comm = float(comm_str)
            
            # Khách nhận 90%, Bạn giữ 10%
            cashback = int(total_comm * 0.90)
            
            user = get_user(target_id)
            old_bal = user.get("balance", 0) if user else 0
            old_orders = user.get("orders", []) if user else []

            # Nếu đơn hàng bị Hủy / Từ chối
            if str(status).lower().strip() in ["0", "cancel", "cancelled", "reject", "rejected", "-1"]:
                new_bal = max(0, old_bal - cashback)
                old_orders.append(f"❌ Đơn Hủy/Hoàn #{order_id}: -{cashback:,.0f} VNĐ")
                save_or_update_user(target_id, balance=new_bal, orders=old_orders)
            else:
                # Cộng tiền vào ví và ghi lịch sử
                new_bal = old_bal + cashback
                old_orders.append(f"🛒 Hoàn tiền đơn #{order_id}: +{cashback:,.0f} VNĐ")
                save_or_update_user(target_id, balance=new_bal, orders=old_orders)
                
                # Gửi tin nhắn thông báo cộng tiền vào ví và số dư mới cho khách ngay lập tức
                bot.send_message(
                    target_id, 
                    f"🎉 **ĐƠN HÀNG ĐÃ ĐƯỢC GHI NHẬN!**\n\n"
                    f"📦 Mã đơn: `{order_id}`\n"
                    f"💰 Tiền hoàn về ví: **+{cashback:,.0f} VNĐ** (90% hoa hồng)\n"
                    f"💳 Số dư hiện tại: **{new_bal:,.0f} VNĐ**\n\n"
                    f"Cảm ơn bạn đã mua hàng!", 
                    parse_mode="Markdown"
                )
        except Exception as e:
            print("Lỗi Postback ACCESSTRADE:", e)
    return "OK", 200

# --- KHỞI CHẠY POLLING Ở LUỒNG NGẦM ---
def run_polling():
    if not bot: return
    try:
        bot.remove_webhook(drop_pending_updates=True)
        time.sleep(1)
    except Exception:
        pass

    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=15, long_polling_timeout=15)
        except Exception as e:
            print(f"Polling reconnecting... ({e})")
            time.sleep(5)

if bot:
    threading.Thread(target=run_polling, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
                                
