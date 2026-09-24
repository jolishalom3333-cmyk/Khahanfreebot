import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import telebot
from urllib.parse import urlparse, parse_qs, quote

# 1. Đọc biến môi trường từ Render
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") or "8860640969"

bot = telebot.TeleBot(TOKEN)
DATA_FILE = "user_data.json"

# 2. Hàm đọc/ghi dữ liệu
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi lưu file: {e}")

user_data = load_data()

# 3. Lớp xử lý Web Server & Tiếp nhận Postback Adpia
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)

            # Lấy thông số từ Adpia (hỗ trợ cả sub_id, subid lẫn utm_source)
            sub_id_list = query_params.get("sub_id") or query_params.get("subid") or query_params.get("utm_source")
            comm_list = query_params.get("commission") or query_params.get("comm")
            status_list = query_params.get("status") or query_params.get("state")
            order_id_list = query_params.get("order_id") or query_params.get("order_code")

            if sub_id_list and comm_list:
                target_id = str(sub_id_list[0]).strip()
                total_comm = float(comm_list[0])
                cashback = int(total_comm * 0.60)
                admin_profit = int(total_comm - cashback)

                status = str(status_list[0]).lower().strip() if status_list else "success"
                order_id = str(order_id_list[0]).strip() if order_id_list else "Mới"

                if target_id not in user_data:
                    user_data[target_id] = {"balance": 0, "orders": []}

                # XỬ LÝ ĐƠN HỦY / TRẢ HÀNG (TRỪ TIỀN)
                if status in ["cancel", "cancelled", "0", "reject", "rejected"]:
                    user_data[target_id]["balance"] = max(0, user_data[target_id]["balance"] - cashback)
                    order_entry = f"❌ Hủy/Hoàn đơn #{order_id}: -{cashback:,} VNĐ"
                    user_data[target_id]["orders"].append(order_entry)
                    save_data(user_data)

                    try:
                        bot.send_message(
                            target_id,
                            f"⚠️ **CẬP NHẬT: ĐƠN HÀNG BỊ HỦY / TRẢ HÀNG!**\n\n"
                            f"📦 Mã đơn: `{order_id}`\n"
                            f"🔻 Khấu trừ: **-{cashback:,} VNĐ** khỏi ví tích lũy.",
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
                                f"🔻 Trừ hoàn khách (60%): -{cashback:,} VNĐ\n"
                                f"🔻 Lợi nhuận Admin giảm (40%): -{admin_profit:,} VNĐ",
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            print(f"Lỗi gửi tin nhắn Admin: {e}")

                # XỬ LÝ ĐƠN MỚI THÀNH CÔNG (CỘNG TIỀN)
                else:
                    user_data[target_id]["balance"] += cashback
                    order_entry = f"🛒 Hoàn tiền đơn #{order_id}: +{cashback:,} VNĐ"
                    user_data[target_id]["orders"].append(order_entry)
                    save_data(user_data)

                    try:
                        bot.send_message(
                            target_id, 
                            f"🎉 **ĐƠN HÀNG MỚI ĐƯỢC GHI NHẬN!**\n\n"
                            f"📦 Mã đơn: `{order_id}`\n"
                            f"💰 Bạn được cộng **+{cashback:,} VNĐ** (60% hoa hồng) vào ví tích lũy!",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"Lỗi gửi tin nhắn khách: {e}")

                    if ADMIN_ID:
                        try:
                            bot.send_message(
                                ADMIN_ID,
                                f"🔔 **CÓ ĐƠN HÀNG MỚI TỪ KHÁCH!**\n\n"
                                f"👤 **ID Khách:** `{target_id}`\n"
                                f"📦 **Mã đơn:** `{order_id}`\n"
                                f"💰 **Hoa hồng Adpia:** {int(total_comm):,} VNĐ\n"
                                f"🎁 **Hoàn cho khách (60%):** +{cashback:,} VNĐ\n"
                                f"💵 **Lợi nhuận Admin (40%):** +{admin_profit:,} VNĐ",
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            print(f"Lỗi gửi tin nhắn Admin: {e}")

        except Exception as e:
            print(f"Lỗi xử lý Postback: {e}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_check():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check, daemon=True).start()

# 4. Các câu lệnh Telegram Bot
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📦 Đơn hàng của tôi", "💳 Ví & Số dư")
    bot.reply_to(message, "👋 Chào mừng bạn! Hãy gửi link Shopee/TikTok để mua hàng hoàn tiền.", reply_markup=markup)

@bot.message_handler(commands=['congtien'])
def cong_tien(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    try:
        parts = message.text.split()
        target_id = parts[1]
        amount = int(parts[2])
        if target_id not in user_data:
            user_data[target_id] = {"balance": 0, "orders": []}
        user_data[target_id]["balance"] += amount
        order_entry = f"➕ Admin cộng tay: +{amount:,} VNĐ"
        user_data[target_id]["orders"].append(order_entry)
        save_data(user_data)
        bot.reply_to(message, f"✅ Đã cộng {amount:,} VNĐ cho ID {target_id}")
        try:
            bot.send_message(target_id, f"🎉 Bạn vừa được Admin cộng +{amount:,} VNĐ vào ví tích lũy!")
        except Exception:
            pass
    except Exception:
        bot.reply_to(message, "⚠️ Cú pháp: /congtien <USER_ID> <SO_TIEN>")

@bot.message_handler(func=lambda msg: msg.text == "📦 Đơn hàng của tôi")
def my_orders(message):
    uid = str(message.from_user.id)
    orders = user_data.get(uid, {}).get("orders", [])
    if not orders:
        bot.reply_to(message, "📦 Bạn chưa có đơn hàng nào được ghi nhận.")
    else:
        recent = orders[-10:]
        msg_text = "📦 **LỊCH SỬ ĐƠN HÀNG:**\n\n" + "\n".join([f"• {item}" for item in recent])
        bot.reply_to(message, msg_text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "💳 Ví & Số dư")
def my_balance(message):
    uid = str(message.from_user.id)
    bal = user_data.get(uid, {}).get("balance", 0)
    bot.reply_to(message, f"💳 **Số dư tích lũy:** {bal:,} VNĐ", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text is not None and msg.text.startswith("http"))
def convert_link(message):
    uid = message.from_user.id
    raw_url = message.text.strip()
    encoded_url = quote(raw_url, safe='')
    link_adpia = f"https://click.adpia.vn/tracking.php?m=shopee&a=A100156876&l=9999&tu={encoded_url}&utm_source={uid}"
    bot.reply_to(message, f"🛍️ <a href='{link_adpia}'><b>LINK MUA HÀNG HOÀN TIỀN 60%</b></a>\n\n👉 <a href='{link_adpia}'>BẤM VÀO ĐÂY ĐỂ MUA HÀNG</a>", parse_mode="HTML")

if __name__ == "__main__":
    bot.infinity_polling()
