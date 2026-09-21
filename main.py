import os
import re
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# 1. Cấu hình Token Telegram & Mã Adpia
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADPIA_ACCOUNT = "A100156876"

bot = telebot.TeleBot(BOT_TOKEN)

# 2. Xử lý Webhook Postback từ Adpia
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path == '/adpia-postback':
            query_params = urllib.parse.parse_qs(parsed_path.query)
            
            order_id = query_params.get('order_id', [''])[0]
            chat_id = query_params.get('utm_source', [''])[0]
            commission = query_params.get('commission', ['0'])[0]
            status = query_params.get('status', ['pending'])[0]

            if chat_id and chat_id.isdigit():
                msg = (
                    f"🎉 Đơn hàng mới được ghi nhận!\n\n"
                    f"📦 Mã đơn: {order_id}\n"
                    f"💰 Hoa hồng dự kiến: {commission} VNĐ\n"
                    f"📌 Trạng thái: {status.upper()}\n\n"
                    f"Cảm ơn bạn đã mua hàng qua Bot!"
                )
                try:
                    bot.send_message(int(chat_id), msg)
                except Exception as e:
                    print(f"Lỗi gửi tin nhắn Postback: {e}")

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Bot Khahanfreebot is running!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    server.serve_forever()

# 3. Lắng nghe tin nhắn từ Telegram
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    try:
        bot.reply_to(
            message,
            "👋 Chào mừng bạn đến với Bot Hoàn Tiền!\n\n"
            "Hãy gửi link sản phẩm Shopee hoặc TikTok Shop vào đây để nhận link tích xu hoàn tiền nhé! 🛍️"
        )
    except Exception as e:
        print(f"Lỗi welcome: {e}")

@bot.message_handler(func=lambda message: True)
def process_link(message):
    try:
        text = message.text
        chat_id = message.chat.id
        
        urls = re.findall(r'https?://[^\s]+', text)
        if not urls:
            bot.reply_to(message, "⚠️ Vui lòng gửi một đường link sản phẩm hợp lệ (Shopee hoặc TikTok Shop).")
            return

        raw_url = urls[0]
        encoded_url = urllib.parse.quote(raw_url, safe='')

        if "shopee" in raw_url.lower() or "shp.ee" in raw_url.lower():
            affiliate_url = (
                f"https://click.adpia.vn/tracking.php?m=shopee&a={ADPIA_ACCOUNT}&l=9999"
                f"&tu={encoded_url}&utm_source={chat_id}"
            )
            platform = "Shopee"
        elif "tiktok" in raw_url.lower():
            affiliate_url = (
                f"https://click.adpia.vn/tracking.php?m=tiktoksharelink&a={ADPIA_ACCOUNT}&l=9999"
                f"&tu={encoded_url}&utm_source={chat_id}"
            )
            platform = "TikTok Shop"
        else:
            bot.reply_to(message, "❌ Hiện tại Bot chỉ hỗ trợ đổi link Shopee và TikTok Shop thôi ạ.")
            return

        # Tạo Nút Bấm Chuyển Hướng Mua Hàng
        markup = InlineKeyboardMarkup()
        btn = InlineKeyboardButton("🛍️ BẤM VÀO ĐÂY ĐỂ MUA HÀNG", url=affiliate_url)
        markup.add(btn)

        reply_text = (
            f"✅ Link mua hàng tích xu/hoàn tiền ({platform})\n\n"
            f"👉 Nhấn vào nút bên dưới để chuyển hướng sang ứng dụng mua hàng:"
        )
        bot.reply_to(message, reply_text, reply_markup=markup)

    except Exception as e:
        print(f"Lỗi xử lý link: {e}")
        bot.reply_to(message, "⚠️ Hệ thống đang xử lý, vui lòng thử lại sau giây lát!")

if __name__ == '__main__':
    server_thread = Thread(target=run_web_server)
    server_thread.start()
    
    print("Bot đang chạy...")
    # Tự động kết nối lại nếu mất mạng hoặc gặp lỗi gián đoạn
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
    
