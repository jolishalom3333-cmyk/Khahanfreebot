import os
import threading
from urllib.parse import quote
from flask import Flask, request
import telebot
from supabase import create_client, Client

# --- 1. CẤU HÌNH BIẾN MÔI TRƯỜNG ---
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID') or "8860640969"
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Kết nối CSDL Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 2. HÀM ĐỌC / GHI DỮ LIỆU TỪ SUPABASE ---
def get_user(user_id):
    try:
        res = supabase.table('users').select('*').eq('id', str(user_id)).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print("Lỗi đọc dữ liệu Supabase:", e)
    return None

def save_or_update_user(user_id, name=None, username=None, balance=None, orders=None):
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

# --- 3. CÁC CÂU LỆNH TELEGRAM BOT ---
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
    bot.reply_to(message, f"👋 Chào mừng {first_name}! Hãy gửi link Shopee/TikTok để mua hàng hoàn tiền.", reply_markup=markup)

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
    bot.reply_to(message, f"💳 **Số dư tích lũy:** {bal:,.0f} VNĐ", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text is not None and msg.text.startswith("http"))
def convert_link(message):
    uid = message.from_user.id
    raw_url = message.text.strip()
    encoded_url = quote(raw_url, safe='')
    link_adpia = f"https://click.adpia.vn/tracking.php?m=shopee&a=A100156876&l=9999&tu={encoded_url}&utm_source={uid}"
    bot.reply_to(message, f"🛍️ <a href='{link_adpia}'><b>LINK MUA HÀNG HOÀN TIỀN 60%</b></a>\n\n👉 <a href='{link_adpia}'>BẤM VÀO ĐÂY ĐỂ MUA HÀNG</a>", parse_mode="HTML")

# --- LỆNH ADMIN ---
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
        order_entry = f"➕ Admin cộng tay: +{amount:,.0f} VNĐ"
        old_orders.append(order_entry)
        
        save_or_update_user(target_id, balance=new_bal, orders=old_orders)
        bot.reply_to(message, f"✅ Đã cộng {amount:,.0f} VNĐ cho ID {target_id}")
        try:
            bot.send_message(target_id, f"🎉 Bạn vừa được Admin cộng +{amount:,.0f} VNĐ vào ví tích lũy!")
        except Exception:
            pass
    except Exception:
        bot.reply_to(message, "⚠️ Cú pháp: `/congtien <USER_ID> <SO_TIEN>`", parse_mode="Markdown")

@bot.message_handler(commands=['danhsach'])
def list_users(message):
    if str(message.from_user.id) != str(ADMIN_ID): return
    try:
        res = supabase.table('users').select('*').execute()
        users = res.data
        if not users:
            bot.reply_to(message, "📂 Chưa có khách hàng nào.")
            return

        msg = "📋 *DANH SÁCH KHÁCH HÀNG & SỐ DƯ:*\n\n"
        for info in users:
            uid = info['id']
            name = info.get("name", "Khách hàng")
            username = f"(@{info['username']})" if info.get("username") else ""
            balance = info.get("balance", 0)
            chat_link = f"tg://user?id={uid}"
            
            msg += f"👤 *[{name}]({chat_link})* {username}\n"
            msg += f"🆔 ID: `{uid}`\n"
            msg += f"💰 Số dư: *{balance:,.0f} VNĐ*\n"
            msg += f"👉 Nhắn nhanh: `/nhan {uid} Nội dung`\n"
            msg += "-------------------------------\n"

        bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
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

# --- 4. WEBHOOK NHẬN ĐƠN HÀNG HOÀN TIỀN TỪ ADPIA ---
@app.route('/', methods=['GET', 'POST'])
def webhook():
    target_id = request.args.get('sub_id') or request.args.get('subid') or request.args.get('utm_source')
    comm_str = request.args.get('commission') or request.args.get('comm') or request.args.get('money')
    status = request.args.get('status') or request.args.get('state') or 'success'
    order_id = request.args.get('order_id') or request.args.get('order_code') or 'Mới'

    if target_id and comm_str:
        try:
            target_id = str(target_id).strip()
            total_comm = float(comm_str)
            cashback = int(total_comm * 0.60)
            admin_profit = int(total_comm - cashback)
            status_clean = str(status).lower().strip()

            user = get_user(target_id)
            old_bal = user.get("balance", 0) if user else 0
            old_orders = user.get("orders", []) if user else []

            # XỬ LÝ ĐƠN HỦY / TRẢ HÀNG (TRỪ TIỀN)
            if status_clean in ["cancel", "cancelled", "0", "reject", "rejected"]:
                new_bal = max(0, old_bal - cashback)
                old_orders.append(f"❌ Hủy/Hoàn đơn #{order_id}: -{cashback:,.0f} VNĐ")
                save_or_update_user(target_id, balance=new_bal, orders=old_orders)

                try:
                    bot.send_message(
                        target_id,
                        f"⚠️ **CẬP NHẬT: ĐƠN HÀNG BỊ HỦY / TRẢ HÀNG!**\n\n"
                        f"📦 Mã đơn: `{order_id}`\n"
                        f"🔻 Khấu trừ: **-{cashback:,.0f} VNĐ** khỏi ví tích lũy.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Lỗi gửi tin nhắn khách: {e}")

                if ADMIN_ID:
                    try:
                        bot.send_message(
                            ADMIN_ID,
                            f"🔻 **BÁO CÓ ĐƠN HÀNG BỊ HỦY!**\n\n"
                            f"👤 ID Khách: `{target_id}`\n"
                            f"📦 Mã đơn: `{order_id}`\n"
                            f"🔻 Trừ hoàn khách (60%): -{cashback:,.0f} VNĐ\n"
                            f"🔻 Lợi nhuận Admin giảm (40%): -{admin_profit:,.0f} VNĐ",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"Lỗi gửi tin nhắn Admin: {e}")

            # XỬ LÝ ĐƠN MỚI THÀNH CÔNG (CỘNG TIỀN)
            else:
                new_bal = old_bal + cashback
                old_orders.append(f"🛒 Hoàn tiền đơn #{order_id}: +{cashback:,.0f} VNĐ")
                save_or_update_user(target_id, balance=new_bal, orders=old_orders)

                try:
                    bot.send_message(
                        target_id, 
                        f"🎉 **ĐƠN HÀNG MỚI ĐƯỢC GHI NHẬN!**\n\n"
                        f"📦 Mã đơn: `{order_id}`\n"
                        f"💰 Bạn được cộng **+{cashback:,.0f} VNĐ** (60% hoa hồng) vào ví tích lũy!",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Lỗi gửi tin nhắn khách: {e}")

                if ADMIN_ID:
                    try:
                        client_name = user.get("name", "Khách hàng") if user else "Khách hàng"
                        client_link = f"tg://user?id={target_id}"

                        bot.send_message(
                            ADMIN_ID,
                            f"🔔 *CÓ ĐƠN HÀNG MỚI TỪ KHÁCH!*\n\n"
                            f"👤 *Khách hàng:* [{client_name}]({client_link})\n"
                            f"🆔 ID Khách: `{target_id}`\n"
                            f"📦 Mã đơn: `{order_id}`\n"
                            f"💰 Hoa hồng Adpia: {int(total_comm):,} VNĐ\n"
                            f"🎁 Hoàn cho khách (60%): +{cashback:,.0f} VNĐ\n"
                            f"💵 Lợi nhuận Admin (40%): +{admin_profit:,.0f} VNĐ",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"Lỗi gửi tin nhắn Admin: {e}")

        except Exception as e:
            print(f"Lỗi xử lý Postback: {e}")

    return "OK", 200

# --- 5. KHỞI CHẠY BOT & FLASK SERVER ---
def run_bot():
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
                    
