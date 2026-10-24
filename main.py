import os
import re
import json
import time
import threading
from datetime import datetime
from urllib.parse import quote, urlparse
from flask import Flask, request
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# 1. CẤU HÌNH BIẾN MÔI TRƯỜNG & KHỞI TẠO
# ==========================================
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID') or "8860640969"
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()

SHOPEE_AFFILIATE_ID = os.environ.get('SHOPEE_AFFILIATE_ID', '17317720169').strip()
RIOHUB_API_KEY = os.environ.get('RIOHUB_API_KEY', '').strip()
ADDLIVETAG_API_KEY = os.environ.get('ADDLIVETAG_API_KEY', '').strip()

# Tỷ lệ Cashback mặc định 70% cho khách (giữ lại 30% phí vận hành)
CASHBACK_RATE = float(os.environ.get('CASHBACK_PERCENT', 70)) / 100.0

# Creator username kết nối trên RioHub
CREATOR_USERNAME = os.environ.get('CREATOR_USERNAME', 'thaonguyen2002').strip()

# Danh sách Base URL chính thức và dự phòng của RioHub theo Spec
RIOHUB_BASE_URLS = [
    "https://riohub.vn/api/v1",
    "https://riohub.riokupon.com/api/v1",
    "https://riohub.riokupon.me/api/v1"
]

bot = telebot.TeleBot(TOKEN) if TOKEN else None
app = Flask(__name__)

# ==========================================
# 2. KẾT NỐI CƠ SỞ DỮ LIỆU SUPABASE
# ==========================================
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL.strip("[]'\" "), SUPABASE_KEY.strip("[]'\" "))
        print("✅ Kết nối Supabase thành công!")
    except Exception as e:
        print(f"❌ Lỗi khởi tạo Supabase: {e}")

def get_user(user_id):
    if not supabase: return None
    try:
        res = supabase.table('users').select('*').eq('id', str(user_id)).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None

def save_or_update_user(user_id, name=None, username=None, balance_shopee=None, balance_tiktok=None, orders_shopee=None, orders_tiktok=None):
    if not supabase: return
    try:
        uid = str(user_id)
        existing = get_user(uid)
        if existing:
            data = {}
            if name is not None: data["name"] = name
            if username is not None: data["username"] = username
            if balance_shopee is not None: data["balance_shopee"] = balance_shopee
            if balance_tiktok is not None: data["balance_tiktok"] = balance_tiktok
            if orders_shopee is not None: data["orders_shopee"] = orders_shopee
            if orders_tiktok is not None: data["orders_tiktok"] = orders_tiktok
            if data:
                supabase.table('users').update(data).eq('id', uid).execute()
        else:
            supabase.table('users').insert({
                "id": uid,
                "name": name or "Khách hàng",
                "username": username or "",
                "balance_shopee": balance_shopee if balance_shopee is not None else 0,
                "balance_tiktok": balance_tiktok if balance_tiktok is not None else 0,
                "orders_shopee": orders_shopee if orders_shopee is not None else [],
                "orders_tiktok": orders_tiktok if orders_tiktok is not None else []
            }).execute()
    except Exception as e:
        print(f"Lỗi lưu user Supabase: {e}")

def log_click(user_id, raw_url):
    if not supabase: return
    try:
        supabase.table('clicks').insert({
            "user_id": str(user_id),
            "original_url": raw_url,
            "created_at": datetime.now().isoformat()
        }).execute()
    except Exception:
        pass

# ==========================================
# 3. HÀM XỬ LÝ CHUYỂN ĐỔI LINK AFFILIATE
# ==========================================

def validate_sub_id(sub_id: str) -> bool:
    if not sub_id or not (1 <= len(sub_id) <= 128):
        return False
    if not re.match(r'^[A-Za-z0-9_.-]+$', sub_id):
        return False
    parts = sub_id.split('-')
    if len(parts) > 5:
        return False
    return True

def createAffiliateLink(product_url_or_id: str, sub_id: str):
    sub_id_str = str(sub_id).strip()
    if not validate_sub_id(sub_id_str):
        return None, "Lỗi: sub_id không đúng quy chuẩn (1-128 ký tự)"

    if not RIOHUB_API_KEY:
        return None, "Hệ thống chưa cài đặt RIOHUB_API_KEY!"

    target_url = product_url_or_id
    if str(target_url).startswith("http"):
        try:
            r_head = requests.head(target_url, allow_redirects=True, timeout=5)
            target_url = r_head.url
        except Exception:
            pass

    endpoint = "/partner/tiktok/affiliate/links"
    payload = {
        "creator_username": CREATOR_USERNAME,
        "sub_id": sub_id_str
    }
    
    if str(target_url).startswith("http"):
        payload["product_url"] = target_url
    else:
        payload["product_id"] = str(target_url)

    headers = {
        "X-Riohub-Api-Key": RIOHUB_API_KEY,
        "Content-Type": "application/json"
    }

    for base_url in RIOHUB_BASE_URLS:
        url = base_url + endpoint
        for attempt in range(3):
            try:
                res = requests.post(url, json=payload, headers=headers, timeout=10)
                if res.status_code == 429:
                    retry_after = int(res.headers.get("Retry-After", 2))
                    time.sleep(retry_after)
                    continue

                if res.status_code == 422:
                    try:
                        err_data = res.json()
                        err_code = err_data.get("error", {}).get("code", "")
                        msg = err_data.get("message", "Tham số không hợp lệ")
                    except:
                        err_code, msg = "", res.text
                    if err_code == "product_not_promotable" or "product_not_promotable" in res.text:
                        return None, "Sản phẩm này hiện không có hoa hồng hoặc bị TikTok hạn chế!"
                    return None, f"Lỗi 422: {msg}"

                if res.status_code in [401, 403, 404]:
                    return None, f"Lỗi xác thực RioHub ({res.status_code})."

                if res.status_code >= 500:
                    return None, f"Lỗi máy chủ RioHub ({res.status_code})."

                if res.status_code == 200:
                    data = res.json()
                    aff_link = data.get("affiliate_link")
                    if aff_link:
                        return aff_link, None
                    return None, "API trả về thành công nhưng thiếu link."

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.SSLError):
                break 
            except Exception:
                return None, "Đã có lỗi xảy ra khi kết nối tới RioHub!"

    return None, "Không thể kết nối tới máy chủ RioHub!"

def clean_shopee_url(raw_url: str) -> str:
    """Mở rộng link ngắn s.shopee.vn/shp.ee và làm sạch các tham số tracking rác"""
    target_url = raw_url.strip()
    
    if "s.shopee" in target_url.lower() or "shp.ee" in target_url.lower():
        try:
            r = requests.head(target_url, allow_redirects=True, timeout=8)
            target_url = r.url
        except Exception:
            try:
                r = requests.get(target_url, allow_redirects=True, timeout=8)
                target_url = r.url
            except Exception:
                pass

    parsed = urlparse(target_url)
    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if clean_url.endswith('/'):
        clean_url = clean_url[:-1]
        
    return clean_url

def convert_shopee_link(original_url: str, user_id: str) -> str:
    """Khởi tạo link Affiliate Shopee chuẩn cơ chế an_redir 2026"""
    try:
        if not SHOPEE_AFFILIATE_ID:
            print("❌ Thiếu SHOPEE_AFFILIATE_ID!")
            return None

        clean_landing_page = clean_shopee_url(original_url)
        encoded_landing = quote(clean_landing_page, safe='')
        
        affiliate_link = (
            f"https://s.shopee.vn/an_redir"
            f"?origin_link={encoded_landing}"
            f"&affiliate_id={SHOPEE_AFFILIATE_ID}"
            f"&sub_id={user_id}"
        )
        return affiliate_link
    except Exception as e:
        print(f"❌ Lỗi tạo link Shopee an_redir: {e}")
        return None

# ==========================================
# 4. BOT TELEGRAM HANDLERS & LỆNH
# ==========================================
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
            f"👋 Chào mừng {first_name} đến với Bot Hoàn Tiền Tự Động!\n\n"
            f"🛒 Cách nhận hoàn tiền {int(CASHBACK_RATE * 100)}%:\n"
            f"1️⃣ Copy link sản phẩm trên Shopee / TikTok Shop.\n"
            f"2️⃣ Gửi link trực tiếp vào đây cho Bot.\n"
            f"3️⃣ Bấm nút mua hàng để được ghi nhận hoàn tiền tự động."
        )
        bot.reply_to(message, welcome_text, reply_markup=markup)
    
    @bot.message_handler(func=lambda msg: msg.text in ["danhsach", "/danhsach", "danh sách", "Danh sách", "📦 Đơn hàng của tôi"])
    def my_orders(message):
        uid = str(message.from_user.id)
        
        # NẾU LÀ ADMIN (CHỦ BOT): BÁO TOÀN BỘ ID KHÁCH HÀNG & SỐ DƯ
        if uid == str(ADMIN_ID):
            if not supabase:
                bot.reply_to(message, "❌ Chưa kết nối cơ sở dữ liệu Supabase!")
                return
            try:
                res = supabase.table('users').select('*').execute()
                users_data = res.data or []
                
                if not users_data:
                    bot.reply_to(message, "📭 Chưa có khách hàng nào trong hệ thống!")
                    return

                text = f"📊 **DANH SÁCH KHÁCH HÀNG & SỐ DƯ ({len(users_data)} người):**\n\n"
                total_all = 0

                for u in users_data:
                    u_id = u.get("id", "N/A")
                    name = u.get("name", "Khách")
                    bal_s = u.get("balance_shopee", 0) or 0
                    bal_t = u.get("balance_tiktok", 0) or 0
                    u_total = bal_s + bal_t
                    total_all += u_total
                    
                    text += f"👤 **ID:** `{u_id}` ({name})\n"
                    text += f"   └ Shopee: {bal_s:,.0f}đ | TikTok: {bal_t:,.0f}đ | **Tổng: {u_total:,.0f}đ**\n"

                text += f"\n💰 **TỔNG SỐ DƯ TOÀN HỆ THỐNG:** `{total_all:,.0f} VNĐ`"
                bot.reply_to(message, text, parse_mode="Markdown")
                return
            except Exception as e:
                bot.reply_to(message, f"❌ Lỗi lấy danh sách: {e}")
                return

        # NẾU LÀ KHÁCH HÀNG THƯỜNG: CHỈ HIỆN LỊCH SỬ CỦA HỌ
        user = get_user(uid)
        orders_s = user.get("orders_shopee", []) if user else []
        orders_t = user.get("orders_tiktok", []) if user else []
        
        text = "📦 **LỊCH SỬ ĐƠN HÀNG CỦA BẠN**:\n\n"
        text += "🛍️ **Shopee:**\n"
        if not orders_s: text += "• Chưa có đơn Shopee nào.\n"
        else: text += "".join([f"• {i}\n" for i in orders_s[-5:]])
            
        text += "\n🎵 **TikTok Shop:**\n"
        if not orders_t: text += "• Chưa có đơn TikTok nào.\n"
        else: text += "".join([f"• {i}\n" for i in orders_t[-5:]])
            
        bot.reply_to(message, text, parse_mode="Markdown")
        

    @bot.message_handler(func=lambda msg: msg.text in ["💳 Ví & Số dư", "/sodu", "/wallet"])
    def my_balance(message):
        user = get_user(message.from_user.id)
        bal_s = user.get("balance_shopee", 0) if user else 0
        bal_t = user.get("balance_tiktok", 0) if user else 0
        total = bal_s + bal_t
        
        text = (
            f"💳 **SỐ DƯ VÍ TÍCH LŨY CỦA BẠN:**\n\n"
            f"🛍️ Số dư Shopee: **{bal_s:,.0f} VNĐ**\n"
            f"🎵 Số dư TikTok: **{bal_t:,.0f} VNĐ**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💰 **Tổng số dư:** `{total:,.0f} VNĐ`"
        )
        bot.reply_to(message, text, parse_mode="Markdown")

        # NẾU LÀ KHÁCH HÀNG THƯỜNG: CHỈ HIỆN LỊCH SỬ CỦA HỌ
        user = get_user(uid)
        orders_s = user.get("orders_shopee", []) if user else []
        orders_t = user.get("orders_tiktok", []) if user else []
        
        text = "📦 **LỊCH SỬ ĐƠN HÀNG CỦA BẠN**:\n\n"
        text += "🛍️ **Shopee:**\n"
        if not orders_s: text += "• Chưa có đơn Shopee nào.\n"
        else: text += "".join([f"• {i}\n" for i in orders_s[-5:]])
            
        text += "\n🎵 **TikTok Shop:**\n"
        if not orders_t: text += "• Chưa có đơn TikTok nào.\n"
        else: text += "".join([f"• {i}\n" for i in orders_t[-5:]])
            
        bot.reply_to(message, text, parse_mode="Markdown")
        
    @bot.message_handler(func=lambda msg: msg.text in ["❓ Hướng dẫn mua hàng", "/huongdan"])
    def guide(message):
        bot.reply_to(message, "📌 Gửi link sản phẩm trực tiếp vào đây để Bot tạo link hoàn tiền tự động nhé!")

    @bot.message_handler(func=lambda msg: msg.text == "💬 Hỗ trợ Admin")
    def support(message):
        bot.reply_to(message, "💬 Gửi nội dung cần hỗ trợ kèm mã đơn vào đây nhé!")

    @bot.message_handler(commands=['pay', 'thanhtoan'])
    def admin_pay(message):
        if str(message.from_user.id) != str(ADMIN_ID):
            bot.reply_to(message, "❌ Bạn không có quyền sử dụng lệnh này!")
            return
            
        parts = message.text.strip().split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Cú pháp sai! Dùng: `/pay <telegram_id>`", parse_mode="Markdown")
            return
            
        target_id = parts[1].strip()
        user = get_user(target_id)
        if not user:
            bot.reply_to(message, f"❌ Không tìm thấy user có ID: `{target_id}` trong hệ thống!", parse_mode="Markdown")
            return
            
        bal_s = user.get("balance_shopee", 0)
        bal_t = user.get("balance_tiktok", 0)
        total_pay = bal_s + bal_t
        
        if total_pay <= 0:
            bot.reply_to(message, f"⚠️ User `{target_id}` không có số dư để thanh toán!", parse_mode="Markdown")
            return

        save_or_update_user(target_id, balance_shopee=0, balance_tiktok=0)
        bot.reply_to(message, f"✅ Đã thanh toán thành công cho User `{target_id}`!\n💵 Đã chuyển khoản và đưa số dư về **0 VNĐ**.", parse_mode="Markdown")
        
        try:
            bot.send_message(
                target_id, 
                f"🎉 **THÔNG BÁO THANH TOÁN THÀNH CÔNG!**\n\n"
                f"Admin đã thanh toán số dư tích lũy vào tài khoản của bạn.\n💳 Số dư ví hiện tại: **0 VNĐ**.", 
                parse_mode="Markdown"
            )
        except Exception:
            pass

    @bot.message_handler(func=lambda msg: msg.text is not None and msg.text.startswith("http"))
    def convert_link(message):
        uid = message.from_user.id
        raw_url = message.text.strip()
        log_click(uid, raw_url)
        
        afflink = None
        platform = ""
        
        if "tiktok" in raw_url.lower():
            platform = "TikTok Shop"
            afflink, err_msg = createAffiliateLink(raw_url, uid)
            if not afflink:
                bot.reply_to(message, f"❌ Lỗi TikTok: {err_msg or 'Không thể tạo link qua RioHub.'}")
                return

        elif "shopee" in raw_url.lower() or "shp.ee" in raw_url.lower():
            platform = "Shopee"
            afflink = convert_shopee_link(raw_url, uid)
            if not afflink:
                bot.reply_to(message, "❌ Lỗi Shopee: Không thể khởi tạo link mua hàng. Vui lòng thử lại sau!")
                return
        else:
            bot.reply_to(message, "⚠️ Bot hiện chỉ hỗ trợ tạo link mua hàng cho Shopee và TikTok Shop!")
            return
            
        inline_kb = InlineKeyboardMarkup()
        btn_buy = InlineKeyboardButton(text=f"🛒 MUA NGAY HOÀN TIỀN {int(CASHBACK_RATE * 100)}%", url=afflink)
        inline_kb.add(btn_buy)
        
        caption_text = (
            f"🎉 **Link hoàn tiền ({platform}) đã sẵn sàng!**\n\n"
            f"💡 Bấm vào nút bên dưới để mở ứng dụng và tiến hành đặt hàng:"
        )
        bot.send_message(message.chat.id, caption_text, parse_mode="Markdown", reply_markup=inline_kb)

# ==========================================
# 5. FLASK WEBHOOK POSTBACK (CỘNG TIỀN TÁCH BIỆT)
# ==========================================
@app.route('/', methods=['GET', 'POST', 'HEAD'])
@app.route('/postback', methods=['GET', 'POST', 'HEAD'])
def webhook():
    if request.method == 'HEAD':
        return "", 200
        
    # Hỗ trợ lấy dữ liệu từ cả GET (request.args) và POST (json/form)
    try:
        if request.method == 'GET':
            data = request.args.to_dict()
        else:
            data = request.get_json(silent=True) or request.form.to_dict()
    except Exception:
        data = {}

    if not data:
        return "No data", 400

    # Lấy thông tin từ thông báo Postback
    user_id = str(data.get("sub_id") or data.get("uid") or data.get("target_id") or "")
    order_id = str(data.get("order_id") or data.get("id") or "")
    try:
        commission = float(data.get("commission") or data.get("amount") or 0)
    except:
        commission = 0
        
    status = str(data.get("status") or "PENDING").upper()
    network = str(data.get("network") or data.get("platform") or "shopee").lower()

    if not user_id:
        return "Missing user_id", 400

    user = get_user(user_id)
    if not user:
        return "User not found", 404

    balance_key = "balance_tiktok" if "tiktok" in network else "balance_shopee"
    orders_key = "orders_tiktok" if "tiktok" in network else "orders_shopee"

    current_balance = user.get(balance_key, 0) or 0
    orders_list = user.get(orders_key, []) or []

    # 1. TRẠNG THÁI: MỚI ĐẶT HÀNG / TẠM TÍNH (PENDING) -> CỘNG TIỀN NGAY LẬP TỨC
    if status in ["PENDING", "NEW", "PROCESSING", "WAITING", "APPROVED"]:
        order_info = f"🛒 Đơn #{order_id}: +{commission:,.0f}đ ({status})"
        # Kiểm tra để tránh cộng trùng lặp nếu postback gửi lại nhiều lần
        if not any(order_id in item for item in orders_list):
            orders_list.append(order_info)
            new_balance = current_balance + commission
            
            # Cập nhật vào Supabase
            supabase.table('users').update({
                balance_key: new_balance,
                orders_key: orders_list
            }).eq('id', user_id).execute()

            # Báo tin nhắn chúc mừng ngay cho khách qua Telegram
            try:
                bot.send_message(
                    user_id, 
                    f"🎉 **GHI NHẬN ĐƠN HÀNG MỚI!**\n\n"
                    f"📦 Mã đơn: `{order_id}`\n"
                    f"💰 Hoa hồng tạm tính: **+{commission:,.0f} VNĐ**\n"
                    f"💳 Số dư hiện tại: **{new_balance:,.0f} VNĐ**\n\n"
                    f"⚡ *Số tiền đã được cộng tạm tính vào tài khoản của bạn!*"
                )
            except Exception as e:
                print(f"Lỗi gửi tin nhắn cho khách: {e}")

    # 2. TRẠNG THÁI: ĐƠN BỊ HỦY / HOÀN (CANCELLED / REJECTED) -> TRỪ LẠI TIỀN
    elif status in ["CANCELLED", "REJECTED", "FAILED"]:
        new_balance = max(0, current_balance - commission)
        order_info = f"❌ Đơn #{order_id}: -{commission:,.0f}đ (Đã hủy)"
        orders_list.append(order_info)

        supabase.table('users').update({
            balance_key: new_balance,
            orders_key: orders_list
        }).eq('id', user_id).execute()

        try:
            bot.send_message(
                user_id,
                f"⚠️ **THÔNG BÁO THAY ĐỔI ĐƠN HÀNG**\n\n"
                f"📦 Đơn hàng `{order_id}` của bạn đã bị hủy/hoàn.\n"
                f"💸 Số tiền tạm tính (-{commission:,.0f}đ) đã được điều chỉnh.\n"
                f"💳 Số dư hiện tại: **{new_balance:,.0f} VNĐ**"
            )
        except Exception as e:
            print(f"Lỗi gửi tin nhắn hủy đơn: {e}")

    return "OK", 200

def run_bot():
    if bot:
        print("🤖 Telegram Bot polling started...")
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                print(f"❌ Lỗi Polling Bot: {e}")
                time.sleep(5)

if __name__ == '__main__':
    if bot:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
