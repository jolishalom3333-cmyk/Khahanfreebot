import os
import re
import json
import time
import threading
from datetime import datetime
from urllib.parse import quote
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

SHOPEE_COOKIE = os.environ.get('SHOPEE_COOKIE', '').strip()
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

def convert_shopee_addlivetag(original_url, user_id):
    if not ADDLIVETAG_API_KEY:
        return None
    url = "https://addlivetag.com/api/v1/shopee/generate-link"
    headers = {
        "X-API-Key": ADDLIVETAG_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "url": original_url,
        "sub_id": str(user_id)
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            return data.get("short_link") or data.get("affiliate_link")
    except Exception:
        pass
    return None

def convert_shopee_cookie(original_url, user_id):
    if not SHOPEE_COOKIE:
        return None
        
    url = "https://affiliate.shopee.vn/api/v3/gql"
    headers = {
        "Cookie": SHOPEE_COOKIE,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://affiliate.shopee.vn/",
        "Origin": "https://affiliate.shopee.vn",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty"
    }
    payload = {
        "query": """
        mutation CustomLink($url: String!,$subId: String) {
            generateCustomLink(input: { originUrl: $url, subId1:$subId }) {
                shortLink
            }
        }
        """,
        "variables": {"url": original_url, "subId": str(user_id)}
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        data = res.json()
        if "data" in data and data["data"] and data["data"].get("generateCustomLink"):
            return data["data"]["generateCustomLink"]["shortLink"]
    except Exception:
        pass
    return None

def convert_shopee_link(original_url, user_id):
    afflink = convert_shopee_addlivetag(original_url, user_id)
    if afflink:
        return afflink
    return convert_shopee_cookie(original_url, user_id)

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

    # Xem lịch sử đơn hàng (Tách biệt Shopee & TikTok)
    @bot.message_handler(func=lambda msg: msg.text in ["📦 Đơn hàng của tôi", "/danhsach", "/donhang"])
    def my_orders(message):
        user = get_user(message.from_user.id)
        orders_s = user.get("orders_shopee", []) if user else []
        orders_t = user.get("orders_tiktok", []) if user else []
        
        text = "📦 **LỊCH SỬ ĐƠN HÀNG CỦA BẠN**:\n\n"
        
        text += "🛍️ **Shopee:**\n"
        if not orders_s:
            text += "• Chưa có đơn Shopee nào.\n"
        else:
            text += "".join([f"• {i}\n" for i in orders_s[-5:]])
            
        text += "\n🎵 **TikTok Shop:**\n"
        if not orders_t:
            text += "• Chưa có đơn TikTok nào.\n"
        else:
            text += "".join([f"• {i}\n" for i in orders_t[-5:]])
            
        bot.reply_to(message, text, parse_mode="Markdown")

    # Xem số dư ví (Tách biệt Shopee & TikTok)
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

    @bot.message_handler(func=lambda msg: msg.text in ["❓ Hướng dẫn mua hàng", "/huongdan"])
    def guide(message):
        bot.reply_to(message, "📌 Gửi link sản phẩm trực tiếp vào đây để Bot tạo link hoàn tiền tự động nhé!")

    @bot.message_handler(func=lambda msg: msg.text == "💬 Hỗ trợ Admin")
    def support(message):
        bot.reply_to(message, "💬 Gửi nội dung cần hỗ trợ kèm mã đơn vào đây nhé!")

    # Lệnh Admin thanh toán: /pay <telegram_id> hoặc /thanhtoan <telegram_id>
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

        # Reset số dư cả 2 sàn về 0
        save_or_update_user(target_id, balance_shopee=0, balance_tiktok=0)
        
        bot.reply_to(message, f"✅ Đã thanh toán thành công cho User `{target_id}`!\n💵 Đã chuyển khoản và đưa số dư Shopee & TikTok về **0 VNĐ**.", parse_mode="Markdown")
        
        # Gửi thông báo về cho người dùng
        try:
            bot.send_message(
                target_id, 
                f"🎉 **THÔNG BÁO THANH TOÁN THÀNH CÔNG!**\n\n"
                f"Admin đã thanh toán số dư tích lũy (Shopee: {bal_s:,.0f}đ | TikTok: {bal_t:,.0f}đ) vào tài khoản ngân hàng của bạn.\n"
                f"💳 Số dư ví hiện tại của bạn đã được reset về: **0 VNĐ**.\n\n"
                f"Cảm ơn bạn đã sử dụng dịch vụ!", 
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

    if request.is_json or request.method == 'POST':
        try:
            data = request.get_json(silent=True) or {}
            if data:
                target_id = str(data.get("sub_id") or data.get("trace_id") or data.get("subid") or "").strip()
                comm = float(data.get("commission") or data.get("pub_commission") or data.get("est_commission") or 0)
                order_id = str(data.get("order_id") or data.get("id") or "Mới")
                event_type = str(data.get("event") or "").lower()
                
                source = str(data.get("source") or "").lower()
                is_tiktok = "tiktok" in source or "riohub" in request.url or "tiktok" in str(data)

                if target_id and comm > 0 and bot:
                    cashback = int(comm * CASHBACK_RATE)
                    user = get_user(target_id)
                    
                    bal_s = user.get("balance_shopee", 0) if user else 0
                    bal_t = user.get("balance_tiktok", 0) if user else 0
                    orders_s = user.get("orders_shopee", []) if user else []
                    orders_t = user.get("orders_tiktok", []) if user else []

                    if is_tiktok:
                        if event_type in ["order.refunded", "cancelled", "rejected"] or data.get("status") == 3:
                            bal_t = max(0, bal_t - cashback)
                            orders_t.append(f"❌ Hủy đơn TikTok #{order_id}: -{cashback:,.0f} VNĐ")
                            save_or_update_user(target_id, balance_tiktok=bal_t, orders_tiktok=orders_t)
                            try:
                                bot.send_message(target_id, f"❌ ĐƠN TIKTOK BỊ HỦY/HOÀN!\nTrừ -{cashback:,.0f} VNĐ cho đơn #{order_id}")
                            except Exception: pass
                        else:
                            bal_t += cashback
                            orders_t.append(f"🛒 Hoàn tiền TikTok #{order_id}: +{cashback:,.0f} VNĐ")
                            save_or_update_user(target_id, balance_tiktok=bal_t, orders_tiktok=orders_t)
                            try:
                                bot.send_message(target_id, f"🎉 CỘNG TIỀN HOÀN (TikTok)!\n💰 +{cashback:,.0f} VNĐ cho đơn #{order_id}")
                            except Exception: pass
                    else:
                        if event_type in ["order.refunded", "cancelled", "rejected"] or data.get("status") == 3:
                            bal_s = max(0, bal_s - cashback)
                            orders_s.append(f"❌ Hủy đơn Shopee #{order_id}: -{cashback:,.0f} VNĐ")
                            save_or_update_user(target_id, balance_shopee=bal_s, orders_shopee=orders_s)
                            try:
                                bot.send_message(target_id, f"❌ ĐƠN SHOPEE BỊ HỦY/HOÀN!\nTrừ -{cashback:,.0f} VNĐ cho đơn #{order_id}")
                            except Exception: pass
                        else:
                            bal_s += cashback
                            orders_s.append(f"🛒 Hoàn tiền Shopee #{order_id}: +{cashback:,.0f} VNĐ")
                            save_or_update_user(target_id, balance_shopee=bal_s, orders_shopee=orders_s)
                            try:
                                bot.send_message(target_id, f"🎉 CỘNG TIỀN HOÀN (Shopee)!\n💰 +{cashback:,.0f} VNĐ cho đơn #{order_id}")
                            except Exception: pass
                return "OK", 200
        except Exception as e:
            print("Lỗi xử lý Postback JSON:", e)

        # Xử lý Query Parameters (GET)
    target_id = request.args.get('sub_id') or request.args.get('utm_source') or request.args.get('subid')
    comm_str = request.args.get('pub_commission') or request.args.get('commission') or request.args.get('est_commission')
    if target_id and comm_str and bot:
        try:
            total_comm = float(comm_str)
            cashback = int(total_comm * CASHBACK_RATE)
            order_id = request.args.get('order_id') or 'Mới'
            source = str(request.args.get('source') or "").lower()
            is_tiktok = "tiktok" in source

            user = get_user(target_id)
            bal_s = user.get("balance_shopee", 0) if user else 0
            bal_t = user.get("balance_tiktok", 0) if user else 0
            orders_s = user.get("orders_shopee", []) if user else []
            orders_t = user.get("orders_tiktok", []) if user else []

            if is_tiktok:
                bal_t += cashback
                orders_t.append(f"🛒 Hoàn tiền TikTok #{order_id}: +{cashback:,.0f} VNĐ")
                save_or_update_user(target_id, balance_tiktok=bal_t, orders_tiktok=orders_t)
                try:
                    bot.send_message(target_id, f"🎉 CỘNG TIỀN HOÀN (TikTok)!\n💰 +{cashback:,.0f} VNĐ cho đơn #{order_id}")
                except Exception: pass
            else:
                bal_s += cashback
                orders_s.append(f"🛒 Hoàn tiền Shopee #{order_id}: +{cashback:,.0f} VNĐ")
                save_or_update_user(target_id, balance_shopee=bal_s, orders_shopee=orders_s)
                try:
                    bot.send_message(target_id, f"🎉 CỘNG TIỀN HOÀN (Shopee)!\n💰 +{cashback:,.0f} VNĐ cho đơn #{order_id}")
                except Exception: pass
        except Exception: pass

    return "Server Cashback đang hoạt động mượt mà!", 200

# Run Bot trên luồng riêng
def run_bot():
    if not bot: return
    try: bot.remove_webhook()
    except Exception: pass
    while True:
        try:
            print("🤖 Đang lắng nghe tin nhắn từ Telegram...")
            bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception as e:
            print(f"❌ Lỗi Polling: {e}")
            time.sleep(5)

threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
