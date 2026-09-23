import os
import json
import telebot
from telebot import types

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID", "8860640969")

bot = telebot.TeleBot(TOKEN)
DATA_FILE = "user_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📦 Đơn hàng của tôi"), types.KeyboardButton("💳 Ví & Số dư"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.from_user.id)
    data = load_data()
    if user_id not in data:
        data[user_id] = {"balance": 0, "orders": []}
        save_data(data)
    bot.reply_to(message, f"👋 Chào {message.from_user.first_name}!\nHãy dán link Shopee/TikTok vào đây để nhận link hoàn tiền 70% nhé.", reply_markup=main_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "📦 Đơn hàng của tôi")
def show_orders(message):
    user_id = str(message.from_user.id)
    data = load_data()
    orders = data.get(user_id, {}).get("orders", [])
    if not orders:
        bot.reply_to(message, "📦 Bạn chưa có đơn hàng nào được ghi nhận.")
        return
    msg_text = "📦 <b>DANH SÁCH ĐƠN HÀNG CỦA BẠN:</b>\n\n"
    total = 0
    for idx, item in enumerate(orders, 1):
        hoan_tien = item.get('hoa_hong_goc', 0) * 0.7
        total += hoan_tien
        msg_text += f"{idx}. Đơn #{item.get('ma_don', 'N/A')}\n   💰 Tiền hoàn 70%: <b>+{hoan_tien:,.0f}đ</b>\n\n"
    msg_text += f"💵 <b>TỔNG TÍCH LŨY: {total:,.0f} VNĐ</b>"
    bot.reply_to(message, msg_text, parse_mode="HTML")

@bot.message_handler(func=lambda msg: msg.text == "💳 Ví & Số dư")
def show_balance(message):
    user_id = str(message.from_user.id)
    data = load_data()
    balance = data.get(user_id, {}).get("balance", 0)
    bot.reply_to(message, f"💳 <b>VÍ VÀ SỐ DƯ</b>\n\n💰 Số dư khả dụng: <b>{balance:,.0f} VNĐ</b>\n\n<i>(Rút tiền vào ngày 30 hàng tháng khi đủ từ 50.000 VNĐ)</i>", parse_mode="HTML")

@bot.message_handler(commands=['congtien'])
def quick_add(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    try:
        parts = message.text.split()
        if len(parts) < 4:
            bot.reply_to(message, "❌ Cú pháp: `/congtien [ID_Khách] [Mã_Đơn] [Hoa_Hồng_Adpia]`", parse_mode="Markdown")
            return
        _, user_id, ma_don, hoa_hong_goc = parts[:4]
        hoa_hong_goc = float(hoa_hong_goc)
        hoa_hong_khach = hoa_hong_goc * 0.7
        data = load_data()
        if user_id not in data:
            data[user_id] = {"balance": 0, "orders": []}
        data[user_id]["balance"] += hoa_hong_khach
        data[user_id]["orders"].append({"ma_don": ma_don, "hoa_hong_goc": hoa_hong_goc})
        save_data(data)
        bot.reply_to(message, f"✅ Đã cộng +{hoa_hong_khach:,.0f}đ cho khách {user_id}")
        bot.send_message(user_id, f"🎉 Đơn hàng <b>#{ma_don}</b> đã ghi nhận thành công!\n💰 Bạn được cộng <b>+{hoa_hong_khach:,.0f}đ</b> hoàn tiền (70%).", parse_mode="HTML")
    except Exception as e:
        bot.reply_to(message, f"❌ Lỗi: {str(e)}")

@bot.message_handler(func=lambda msg: msg.text and msg.text.startswith("http"))
def convert_link(message):
    user_id = message.from_user.id
    link_adpia = f"https://click.adpia.vn/click.php?m=shoppemcn&a=MA_AFFILIATE_CUABAN&sub_id={user_id}&url={message.text.strip()}"
    bot.reply_to(message, f"🛍️ <b>LINK MUA HÀNG HOÀN TIỀN 70%</b>\n\n👉 <a href='{link_adpia}'>BẤM VÀO ĐÂY ĐỂ MUA HÀNG</a>", parse_mode="HTML")

if __name__ == "__main__":
    bot.infinity_polling()
    
