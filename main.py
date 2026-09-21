import os
import re
import sqlite3
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# 1. Cấu hình Token Telegram & Mã Adpia
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADPIA_ACCOUNT = "A100156876"

bot = telebot.TeleBot(BOT_TOKEN)

# 2. Khởi tạo Cơ sở dữ liệu ngầm (Lưu đơn hàng không thông báo)
def init_db():
    conn = sqlite3.connect('orders.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            order_id TEXT,
            commission REAL,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_order(chat_id, order_id, commission, status):
    try:
        conn = sqlite3.connect('orders.db')
        cursor = conn.cursor()
        # Kiểm tra xem đơn đã tồn tại chưa để cập nhật trạng thái hoặc thêm mới
        cursor.execute("SELECT id FROM orders WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE orders SET status = ?, commission = ? WHERE order_id = ?", (status, commission, order_id))
        else:
            cursor.execute("INSERT INTO orders (chat_id, order_id, commission, status) VALUES (?, ?, ?, ?)",
                           (str(chat_id), str(order_id), float(commission), str(status)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Lỗi lưu DB: {e}")

def get_user_orders(chat_id):
    try:
        conn = sqlite3.connect('orders.db')
        cursor = conn.cursor()
        cursor.execute("SELECT order_id, commission, status, created_at FROM orders WHERE chat_id = ? ORDER BY id DESC LIMIT 10", (str(chat_id),))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Lỗi đọc DB: {e}")
        return []

# 3. Webhook nhận tin từ Adpia (LƯU NGẦM - KHÔNG GỬI TIN NHẮN)
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path == '/adpia-postback':
            query_params = urllib.parse.parse_qs(parsed_path.query)
            
            order_id = query_params.get('order_id', [''])[0]
            chat_id = query_params.get('utm_source', [''])[0]
            commission = query_params.get('commission', ['0'])[0]
            status = query_params.get('status', ['pending'])[0]

            if chat_id and order_id:
                # Chỉ lưu ngầm vào CSDL, hoàn toàn không gọi bot.send_message
                save_order(chat_id, order_id, commission, status)

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Bot is running!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    server.serve_forever()

# 4. Tạo Menu nút bấm cố định cho khách hàng
def get_main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    btn_orders = KeyboardButton("📦 Đơn hàng của tôi")
    btn_wallet = KeyboardButton("💳 Ví & Số dư")
    markup.row(btn_orders, btn_wallet)
    return markup

# 5. Xử lý lệnh từ người dùng
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    try:
        bot.reply_to(
            message,
            "👋 <b>Chào mừng bạn đến với Bot Hoàn Tiền!</b>\n\n"
            "📌 <b>Cách dùng:</b>\n"
            "1. Gửi link sản phẩm Shopee hoặc TikTok Shop vào đây để lấy link mua hàng.\n"
            "2. Sử dụng menu bên dưới để tự kiểm tra đơn hàng và số dư hoàn tiền bất cứ lúc nào!",
            parse_mode='HTML',
            reply_markup=get_main_menu()
        )
    except Exception as e:
        print(f"Lỗi welcome: {e}")

@bot.message_handler(func=lambda message: message.text == "📦 Đơn hàng của tôi")
def show_orders(message):
    chat_id = message.chat.id
    orders = get_user_orders(chat_id)
    
    if not orders:
        bot.reply_to(message, "📂 Bạn chưa có đơn hàng nào được ghi nhận.\nHãy dán link sản phẩm vào Bot và mua hàng để nhận hoàn tiền nhé!", reply_markup=get_main_menu())
        return

    msg = "📋 <b>DANH SÁCH ĐƠN HÀNG CỦA BẠN:</b>\n\n"
    for item in orders:
        order_id, comm, status, created_at = item
        status_text = "⏳ Tạm tính" if status.lower() == 'pending' else "✅ Đã duyệt"
        # Chia 60% cho khách
        user_cashback = float(comm) * 0.6
        msg += f"📦 Mã đơn: <code>{order_id}</code>\n"
        msg += f"💰 Hoàn tiền: <b>{user_cashback:,.0f}đ</b> ({status_text})\n"
        msg += f"------------------------\n"

    bot.reply_to(message, msg, parse_mode='HTML', reply_markup=get_main_menu())

@bot.message_handler(func=lambda message: message.text == "💳 Ví & Số dư")
def show_wallet(message):
    chat_id = message.chat.id
    orders = get_user_orders(chat_id)
    
    pending_total = 0
    approved_total = 0
    
    for item in orders:
        _, comm, status, _ = item
        user_cashback = float(comm) * 0.6
        if status.lower() == 'pending':
            pending_total += user_cashback
        else:
            approved_total += user_cashback

    msg = (
        f"💳 <b>THÔNG TIN VÍ HOÀN TIỀN</b>\n\n"
        f"⏳ <b>Tiền chờ duyệt (Tạm tính):</b> {pending_total:,.0f}đ\n"
        f"✅ <b>Số dư khả dụng (Được rút):</b> {approved_total:,.0f}đ\n\n"
        f"<i>(Số dư khả dụng từ 50.000đ có thể liên hệ Admin để rút về ngân hàng)</i>"
    )
    bot.reply_to(message, msg, parse_mode='HTML', reply_markup=get_main_menu())

@bot.message_handler(func=lambda message: True)
def process_link(message):
    try:
        text = message.text
        chat_id = message.chat.id
        
        # Nếu bấm các nút menu thì bỏ qua không xử lý dạng link
        if text in ["📦 Đơn hàng của tôi", "💳 Ví & Số dư"]:
            return

        urls = re.findall(r'https?://[^\s]+', text)
        if not urls:
            bot.reply_to(message, "⚠️ Vui lòng gửi một đường link Shopee hoặc TikTok Shop hợp lệ.", reply_markup=get_main_menu())
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
            bot.reply_to(message, "❌ Bot hiện hỗ trợ link Shopee và TikTok Shop.", reply_markup=get_main_menu())
            return

        reply_text = (
            f"🛍️ <b>LINK MUA HÀNG HOÀN TIỀN ({platform.upper()})</b>\n\n"
            f"🌸 <b>Hoa hồng dự kiến:</b> Lên đến 15%\n"
            f"⚡ <b>Trạng thái:</b> Đã kích hoạt tích xu"
        )
        
        markup = InlineKeyboardMarkup()
        btn = InlineKeyboardButton("👉 BẤM VÀO ĐÂY ĐỂ MUA HÀNG", url=affiliate_url)
        markup.add(btn)

        bot.reply_to(message, reply_text, parse_mode='HTML', reply_markup=markup)

    except Exception as e:
        print(f"Lỗi xử lý link: {e}")

if __name__ == '__main__':
    server_thread = Thread(target=run_web_server)
    server_thread.start()
    
    print("Bot đang chạy...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
    
