import os
import re
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import telebot

# 1. Cấu hình Token Telegram & Mã Adpia
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8667094035:AAE5-ZvNAdc96n1C-a5n1MMnZJRaFAnqOWo")
ADPIA_ACCOUNT = "A100156876"

bot = telebot.TeleBot(BOT_TOKEN)

# 2. Xử lý Webhook Postback từ Adpia
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        
        # Nếu Adpia gọi vào đường dẫn /adpia-postback
        if parsed_path.path == '/adpia-postback':
            query_params = urllib.parse.parse_qs(parsed_path.query)
            
            order_id = query_params.get('order_id', [''])[0]
            chat_id = query_params.get('utm_source', [''])[0]
            commission = query_params.get('commission', ['0'])[0]
            status = query_params.get('status', ['pending'])[0]

            # Gửi tin nhắn thông báo về Telegram cho khách hàng
            if chat_id and chat_id.isdigit():
                msg = (
                    f"🎉 **Đơn hàng mới được ghi nhận!**\n\n"
                    f"📦 **Mã đơn:** `{order_id}`\n"
                    f"💰 **Hoa hồng dự kiến:** {commission} VNĐ\n"
                    f"📌 **Trạng thái:** {status.upper()}\n\n"
                    f"Cảm ơn bạn đã mua hàng qua Bot!"
                )
                try:
                    bot.send_message(int(chat_id), msg, parse_mode='Markdown')
                except Exception as e:
                    print(f"Lỗi gửi tin nhắn Telegram: {e}")

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
    bot.reply_to(
        message,
        "👋 **Chào mừng bạn đến với Khahanfreebot - Bot Hoàn Tiền!**\n\n"
        "Hãy gửi link sản phẩm **Shopee** hoặc **TikTok Shop** vào đây, "
        "Bot sẽ tạo link mua hàng hoàn tiền cho bạn nhé! 🛍️"
    )

@bot.message_handler(func=lambda message: True)
def process_link(message):
    text = message.text
    chat_id = message.chat.id
    
    # Tìm link trong tin nhắn
    urls = re.findall(r'https?://[^\s]+', text)
    if not urls:
        bot.reply_to(message, "⚠️ Vui lòng gửi một đường link sản phẩm hợp lệ (Shopee hoặc TikTok Shop).")
        return

    raw_url = urls[0]
    encoded_url = urllib.parse.quote(raw_url, safe='')

    # Kiểm tra loại link Shopee hay TikTok
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

    reply_text = (
        f"✅ **Link mua hàng tích xu/hoàn tiền ({platform}):**\n\n"
        f"🔗 {affiliate_url}\n\n"
        f"👉 Hãy bấm vào link trên để tiến hành mua hàng. Sau khi đặt thành công, hệ thống sẽ tự động gửi thông báo tích xu về đây cho bạn!"
    )
    bot.reply_to(message, reply_text, parse_mode='Markdown')

if __name__ == '__main__':
    # Chạy Web Server nhận Postback ở luồng riêng
    server_thread = Thread(target=run_web_server)
    server_thread.start()
    
    # Chạy Bot Telegram
    print("Bot đang chạy...")
    bot.polling(none_stop=True)
    
