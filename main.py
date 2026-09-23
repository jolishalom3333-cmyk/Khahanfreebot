import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import telebot
from urllib.parse import urlparse, parse_qs

# 1. Đọc biến môi trường từ Render
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

bot = telebot.TeleBot(TOKEN)
DATA_FILE = "user_data.json"

# 2. Hàm đọc/ghi dữ liệu (Khai báo trước để toàn hệ thống dùng chung)
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

# Tải dữ liệu sẵn vào bộ nhớ ngay khi khởi động
user_data = load_data()

# 3. Lớp xử lý Web (Duy trì Render + Tiếp nhận Postback Adpia)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Phân tích dữ liệu Postback gửi về từ Adpia
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)

            sub_id_list = query_params.get("sub_id") or query_params.get("subid")
            comm_list = query_params.get("commission") or query_params.get("comm")

            if sub_id_list and comm_list:
                target_id = str(sub_id_list[0]).strip()
                total_comm = float(comm_list[0])
                
                # Tính 70% hoa hồng hoàn lại cho khách
                cashback = int(total_comm * 0.70)

                if cashback > 0 and target_id:
                    if target_id not in user_data:
                        user_data[target_id] = {"balance": 0, "orders": []}

                    # Cập nhật trực tiếp vào ví trong bộ nhớ & lưu lại file
                    user_data[target_id]["balance"] += cashback
                    user_data[target_id]["orders"].append(f"🛒 Hoàn tiền đơn mới: +{cashback:,} VNĐ")
                    save_data(user_data)

                    # Tự động gửi tin nhắn Telegram báo cho khách
                    try:
                        bot.send_message(
                            target_id, 
                            f"🎉 **ĐƠN HÀNG MỚI ĐƯỢC GHI NHẬN!**\n\n"
                            f"💰 Bạn được cộng **+{cashback:,} VNĐ** (70% hoa hồng) vào ví tích lũy!",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"Lỗi gửi tin nhắn cho khách {target_id}: {e}")

        except Exception as e:
            print(f"Lỗi xử lý Postback: {e}")

        # Luôn luôn trả về kết quả OK để Render duy trì trạng thái Live
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_check():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Chạy cổng web ẩn ở background
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
        save_data(user_data)
        bot.reply_to(message, f"✅ Đã cộng {amount:,} VNĐ cho ID {target_id}")
        try:
            bot.send_message(target_id, f"🎉 Bạn vừa được cộng {amount:,} VNĐ vào tài khoản!")
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
        msg_text = "📦 **Danh sách đơn hàng:**\n" + "\n".join(orders)
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
    link_adpia = f"https://click.adpia.vn/click.php?m=shoppemcn&a=MA_AFFILIATE_CUABAN&sub_id={uid}&url={raw_url}"
    bot.reply_to(message, f"🛍️ <a href='{link_adpia}'><b>LINK MUA HÀNG HOÀN TIỀN 70%</b></a>\n\n👉 <a href='{link_adpia}'>BẤM VÀO ĐÂY ĐỂ MUA HÀNG</a>", parse_mode="HTML")

if __name__ == "__main__":
    bot.infinity_polling()
    
