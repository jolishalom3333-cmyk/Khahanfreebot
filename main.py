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

# ==========================================
# 1. CẤU HÌNH BIẾN MÔI TRƯỜNG & KHỞI TẠO
# ==========================================
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID') or "8860640969"
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()

SHOPEE_COOKIE = os.environ.get('SHOPEE_COOKIE', '').strip()
RIOHUB_API_KEY = os.environ.get('RIOHUB_API_KEY', '').strip()
CASHBACK_RATE = float(os.environ.get('CASHBACK_PERCENT', 90)) / 100.0

# Creator username kết nối trên RioHub
CREATOR_USERNAME = os.environ.get('CREATOR_USERNAME', 'thaonguyen2002').strip()

# Danh sách Base URL chính thức của RioHub theo tài liệu API[span_4](start_span)[span_4](end_span)[span_5](start_span)[span_5](end_span)
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

def save_or_update_user(user_id, name=None, username=None, balance=None, orders=None):
    if not supabase: return
    try:
        uid = str(user_id)
        existing = get_user(uid)
        if existing:
            data = {}
            if name is not None: data["name"] = name
            if username is not None: data["username"] = username
            if balance is not None: data["balance"] = balance
            if orders is not None: data["orders"] = orders
            if data:
                supabase.table('users').update(data).eq('id', uid).execute()
        else:
            supabase.table('users').insert({
                "id": uid,
                "name": name or "Khách hàng",
                "username": username or "",
                "balance": balance if balance is not None else 0,
                "orders": orders if orders is not None else []
            }).execute()
    except Exception:
        pass

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
    """ Kiểm tra quy tắc sub_id theo chuẩn RioHub """
    if not sub_id or not (1 <= len(sub_id) <= 128):
        return False
    if not re.match(r'^[A-Za-z0-9_.-]+$', sub_id):
        return False
    parts = sub_id.split('-')
    if len(parts) > 5:
        return False
    return True

def convert_tiktok_riohub(product_url_or_id: str, sub_id: str):
    """ Tạo link TikTok qua API RioHub sử dụng endpoint chuẩn /partner/tiktok/affiliate/links[span_6](start_span)[span_6](end_span) """
    sub_id_str = str(sub_id)
    if not validate_sub_id(sub_id_str):
        print(f"❌ Lỗi sub_id không hợp lệ: {sub_id_str}")
        return None, "Lỗi sub_id không hợp lệ theo quy chuẩn!"

    if not RIOHUB_API_KEY:
        print("❌ Chưa cấu hình RIOHUB_API_KEY!")
        return None, "Hệ thống chưa cài đặt RIOHUB_API_KEY!"

    endpoints = [
        "/partner/tiktok/affiliate/links",
        "/partner/tiktok/affiliate/product-links"
    ]
    
    payload = {
        "creator_username": CREATOR_USERNAME,
        "sub_id": sub_id_str
    }
    
    if str(product_url_or_id).startswith("http"):
        payload["product_url"] = product_url_or_id
    else:
        payload["product_id"] = str(product_url_or_id)

    headers = {
        "X-Riohub-Api-Key": RIOHUB_API_KEY,
        "Content-Type": "application/json"
    }

    for base_url in RIOHUB_BASE_URLS:
        for endpoint in endpoints:
            url = base_url + endpoint
            for attempt in range(2):
                try:
                    res = requests.post(url, json=payload, headers=headers, timeout=10)
                    print(f"🔎 [RioHub {endpoint}] Status Code: {res.status_code}")
                    
                    if res.status_code == 429:
                        retry_after = int(res.headers.get("Retry-After", 2))
                        print(f"⚠️ RioHub 429 Rate Limited, chờ {retry_after}s...")
                        time.sleep(retry_after)
                        continue

                    if res.status_code == 422:
                        err_data = res.json()
                        err_code = err_data.get("error", {}).get("code", "")
                        if err_code == "product_not_promotable" or "product_not_promotable" in res.text:
                            return None, "Sản phẩm này hiện không có hoa hồng, chưa được shop duyệt hoặc bị TikTok hạn chế!"
                        return None, f"Lỗi 422: {err_data.get('message', 'Tham số không hợp lệ')}"

                    if res.status_code in [401, 403, 404]:
                        print(f"❌ RioHub lỗi {res.status_code} tại {endpoint} - Response: {res.text}")
                        # Thử endpoint tiếp theo nếu lỗi 404
                        if res.status_code == 404:
                            break
                        return None, f"Lỗi xác thực RioHub ({res.status_code})"

                    if res.status_code == 200:
                        data = res.json()
                        aff_link = data.get("affiliate_link") or data.get("short_link") or data.get("link")
                        if aff_link:
                            return aff_link, None

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                    print(f"⚠️ Kết nối tới {url} thất bại...")
                    break
                except Exception as e:
                    print("❌ Lỗi gọi RioHub API:", e)
                    break

    return None, "Không thể kết nối tới máy chủ RioHub hoặc link không hợp lệ!"

def convert_shopee_cookie(original_url, user_id):
    """ Tạo link Shopee bằng Cookie GraphQL """
    if not SHOPEE_COOKIE:
        print("❌ Chưa cấu hình SHOPEE_COOKIE!")
        return None
        
    url = "https://affiliate.shopee.vn/api/v3/gql"
    headers = {
        "Cookie": SHOPEE_COOKIE,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
        print(f"🔎 [Shopee API Status]: {res.status_code}")
        
        data = res.json()
        if "data" in data and data["data"] and data["data"].get("generateCustomLink"):
            return data["data"]["generateCustomLink"]["shortLink"]
        else:
            print(f"⚠️ Shopee trả về lỗi dữ liệu: {data}")
    except Exception as e:
        print("❌ Lỗi Shopee Cookie:", e)
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
            f"3️⃣ Bấm link rút gọn Bot trả về để mua hàng."
        )
        bot.reply_to(message, welcome_text, reply_markup=markup)

    @bot.message_handler(func=lambda msg: msg.text == "📦 Đơn hàng của tôi")
    def my_orders(message):
        user = get_user(message.from_user.id)
        orders = user.get("orders", []) if user else []
        if not orders:
            bot.reply_to(message, "📦 Bạn chưa có đơn hàng nào được ghi nhận.")
        else:
            bot.reply_to(message, "📦 LỊCH SỬ ĐƠN HÀNG:\n\n" + "\n".join([f"• {i}" for i in orders[-10:]]))

    @bot.message_handler(func=lambda msg: msg.text == "💳 Ví & Số dư")
    def my_balance(message):
        user = get_user(message.from_user.id)
        bal = user.get("balance", 0) if user else 0
        bot.reply_to(message, f"💳 SỐ DƯ VÍ TÍCH LŨY: {bal:,.0f} VNĐ")

    @bot.message_handler(func=lambda msg: msg.text in ["❓ Hướng dẫn mua hàng", "/huongdan"])
    def guide(message):
        bot.reply_to(message, "📌 Gửi link sản phẩm trực tiếp vào đây để Bot tạo link hoàn tiền tự động nhé!")

    @bot.message_handler(func=lambda msg: msg.text == "💬 Hỗ trợ Admin")
    def support(message):
        bot.reply_to(message, "💬 Gửi nội dung cần hỗ trợ kèm mã đơn vào đây nhé!")

    @bot.message_handler(func=lambda msg: msg.text is not None and msg.text.startswith("http"))
    def convert_link(message):
        uid = message.from_user.id
        raw_url = message.text.strip()
        log_click(uid, raw_url)
        
        afflink = None
        platform = ""
        
        # 1. Link TikTok Shop
        if "tiktok" in raw_url.lower():
            platform = "TikTok Shop"
            afflink, err_msg = convert_tiktok_riohub(raw_url, uid)
            if not afflink:
                # Sử dụng text thuần túy để tránh lỗi 400 Bad Request từ Markdown
                bot.reply_to(message, f"❌ Lỗi TikTok: {err_msg or 'Không thể tạo link qua RioHub.'}")
                return

        # 2. Link Shopee
        elif "shopee" in raw_url.lower() or "shp.ee" in raw_url.lower():
            platform = "Shopee"
            afflink = convert_shopee_cookie(raw_url, uid)
            if not afflink:
                bot.reply_to(message, "❌ Lỗi Shopee: Cookie hết hạn hoặc không hợp lệ. Vui lòng báo Admin!")
                return
        else:
            bot.reply_to(message, "⚠️ Bot hiện chỉ hỗ trợ tạo link mua hàng cho Shopee và TikTok Shop!")
            return
            
        bot.reply_to(message, f"🛍️ Bấm vào đây để mua hàng hoàn tiền ({platform}):\n{afflink}")

# ==========================================
# 5. FLASK WEBHOOK POSTBACK (CỘNG TIỀN ĐƠN HÀNG)
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

                if target_id and comm > 0 and bot:
                    cashback = int(comm * CASHBACK_RATE)
                    user = get_user(target_id)
                    old_bal = user.get("balance", 0) if user else 0
                    old_orders = user.get("orders", []) if user else []

                    if event_type in ["order.refunded", "cancelled", "rejected"] or data.get("status") == 3:
                        new_bal = max(0, old_bal - cashback)
                        old_orders.append(f"❌ Hủy đơn #{order_id}: -{cashback:,.0f} VNĐ")
                        save_or_update_user(target_id, balance=new_bal, orders=old_orders)
                        try:
                            bot.send_message(target_id, f"❌ ĐƠN HÀNG BỊ HỦY/HOÀN!\nTrừ -{cashback:,.0f} VNĐ cho đơn #{order_id}")
                        except Exception: pass
                    else:
                        new_bal = old_bal + cashback
                        old_orders.append(f"🛒 Hoàn tiền #{order_id}: +{cashback:,.0f} VNĐ")
                        save_or_update_user(target_id, balance=new_bal, orders=old_orders)
                        try:
                            bot.send_message(target_id, f"🎉 CỘNG TIỀN HOÀN!\n💰 +{cashback:,.0f} VNĐ cho đơn #{order_id}")
                        except Exception: pass
                return "OK", 200
        except Exception as e:
            print("Lỗi xử lý Postback:", e)

    target_id = request.args.get('sub_id') or request.args.get('utm_source') or request.args.get('subid')
    comm_str = request.args.get('pub_commission') or request.args.get('commission') or request.args.get('est_commission')
    if target_id and comm_str and bot:
        try:
            total_comm = float(comm_str)
            cashback = int(total_comm * CASHBACK_RATE)
            order_id = request.args.get('order_id') or 'Mới'
            user = get_user(target_id)
            old_bal = user.get("balance", 0) if user else 0
            old_orders = user.get("orders", []) if user else []
            new_bal = old_bal + cashback
            old_orders.append(f"🛒 Hoàn tiền đơn #{order_id}: +{cashback:,.0f} VNĐ")
            save_or_update_user(target_id, balance=new_bal, orders=old_orders)
            try:
                bot.send_message(target_id, f"🎉 CỘNG TIỀN HOÀN!\n💰 +{cashback:,.0f} VNĐ cho đơn #{order_id}")
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

threading.Thread(target=run_bot, daemon=True).sub_id = None
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
        
