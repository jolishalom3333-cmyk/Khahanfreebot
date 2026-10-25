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
# 4. BOT TELEGRAM HANDLERS & LỆNH (2 NÚT MỚI)
# ==========================================
if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        uid = str(message.chat.id)
        first_name = message.from_user.first_name or "Khách"
        username = message.from_user.username or ""
        save_or_update_user(uid, name=first_name, username=username)

        # 2 nút bấm dưới khung chat đúng theo yêu cầu
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("💳 Số dư ví", "💸 Rút tiền")

        welcome_text = (
            f"👋 Chào mừng {first_name} đến với Bot Hoàn Tiền Tự Động!\n\n"
            f"🛒 Cách nhận hoàn tiền {int(CASHBACK_RATE * 100)}%:\n"
            f"1️⃣ Copy link sản phẩm trên Shopee / TikTok Shop.\n"
            f"2️⃣ Gửi link trực tiếp vào đây cho Bot.\n"
            f"3️⃣ Bấm nút mua hàng để được ghi nhận hoàn tiền tự động."
        )
        bot.reply_to(message, welcome_text, reply_markup=markup)

    @bot.message_handler(func=lambda msg: msg.text in ["💳 Số dư ví", "/sodu", "/wallet", "💳 Số dư & Rút tiền"])
    def my_balance(message):
        uid = str(message.from_user.id)
        user = get_user(uid)
        bal_s = user.get("balance_shopee", 0) if user else 0
        bal_t = user.get("balance_tiktok", 0) if user else 0
        total = bal_s + bal_t
        
        text = (
            f"💳 **SỐ DƯ VÍ TÍCH LŨY CỦA BẠN:**\n\n"
            f"🛍️ Số dư Shopee: **{bal_s:,.0f} VNĐ**\n"
            f"🎵 Số dư TikTok: **{bal_t:,.0f} VNĐ**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💰 **Tổng số dư ví:** `{total:,.0f} VNĐ`\n\n"
            f"💡 *Số tiền đã tự động cộng/trừ theo trạng thái đơn hàng thực tế của riêng bạn.*"
        )
        bot.reply_to(message, text, parse_mode="Markdown")

        orders_s = user.get("orders_shopee", []) if user else []
        orders_t = user.get("orders_tiktok", []) if user else []
        
        history_text = "📦 **LỊCH SỬ GIAO DỊCH ĐƠN HÀNG CỦA BẠN**:\n\n"
        history_text += "🛍️ **Shopee:**\n"
        if not orders_s: history_text += "• Chưa có đơn Shopee nào.\n"
        else: history_text += "".join([f"• {i}\n" for i in orders_s[-5:]])
            
        history_text += "\n🎵 **TikTok Shop:**\n"
        if not orders_t: history_text += "• Chưa có đơn TikTok nào.\n"
        else: history_text += "".join([f"• {i}\n" for i in orders_t[-5:]])
            
        bot.reply_to(message, history_text, parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text in ["💸 Rút tiền", "/ruttien"])
    def request_withdrawal(message):
        uid = str(message.from_user.id)
        user = get_user(uid)
        bal_s = user.get("balance_shopee", 0) if user else 0
        bal_t = user.get("balance_tiktok", 0) if user else 0
        total = bal_s + bal_t

        if total <= 0:
            bot.reply_to(message, "⚠️ Số dư ví của bạn hiện đang là **0 VNĐ**, chưa đủ điều kiện để rút tiền!")
            return

        msg = (
            f"💸 **YÊU CẦU RÚT TIỀN HOA HỒNG**\n\n"
            f"💳 Tổng số dư ví hiện có thể rút: **{total:,.0f} VNĐ**\n\n"
            f"👉 **Hướng dẫn:** Vui lòng nhắn tin trực tiếp vào đây thông tin nhận tiền của bạn theo mẫu:\n"
            f"• **Tên ngân hàng:**\n"
            f"• **Số tài khoản:**\n"
            f"• **Tên chủ tài khoản:** (Ví dụ: NGO THI LIEN)\n\n"
            f"⏳ Sau khi bạn gửi thông tin, hệ thống sẽ chuyển tiếp ngay cho Admin để xét duyệt và chuyển khoản cho bạn!"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
        
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
# 5. FLASK WEBHOOK POSTBACK (ĐÃ TÍCH HỢP LOG DEBUG RIOHUB)
# ==========================================
@app.route('/', methods=['GET', 'POST', 'HEAD'])
@app.route('/postback', methods=['GET', 'POST', 'HEAD'])
@app.route('/tiktok-postback', methods=['GET', 'POST', 'HEAD'])
def webhook():
    if request.method == 'HEAD':
        return "", 200
        
    print(f"📥 Nhận request từ RioHub - Method: {request.method}")
    
    data = {}
    try:
        if request.method == 'GET':
            data = request.args.to_dict()
        else:
            data = request.get_json(silent=True) or request.form.to_dict() or {}
    except Exception as e:
        print(f"❌ Lỗi đọc JSON/Form: {e}")

    print(f"📥 Dữ liệu RioHub gửi sang: {data}")

    if not data:
        return "No data", 400

    user_id = str(
        data.get("sub_id") or 
        data.get("uid") or 
        data.get("target_id") or 
        data.get("click_id") or 
        data.get("customer_id") or ""
    ).strip()
    
    order_id = str(data.get("order_id") or data.get("id") or data.get("trans_id") or "UNKNOWN")
    try:
        commission = float(data.get("commission") or data.get("amount") or data.get("payout") or 0)
    except:
        commission = 0
        
    status = str(data.get("status") or data.get("order_status") or "PENDING").upper()
    network = str(data.get("network") or data.get("platform") or "shopee").lower()

    if not user_id:
        print(f"⚠️ Cảnh báo: Không tìm thấy user_id/sub_id trong data: {data}")
        return "Missing user_id", 200

    user = get_user(user_id)
    if not user:
        print(f"⚠️ Cảnh báo: Không tìm thấy user trong database với ID: {user_id}")
        return "User not found", 200

    balance_key = "balance_tiktok" if "tiktok" in network else "balance_shopee"
    orders_key = "orders_tiktok" if "tiktok" in network else "orders_shopee"

    current_balance = user.get(balance_key, 0) or 0
    orders_list = user.get(orders_key, []) or []

    # 1. TRẠNG THÁI: MỚI ĐẶT HÀNG / TẠM TÍNH (PENDING) -> CỘNG TIỀN NGAY
    if status in ["PENDING", "NEW", "PROCESSING", "WAITING", "APPROVED", "SUCCESS"]:
        order_info = f"🛒 Đơn #{order_id}: +{commission:,.0f}đ ({status})"
        if not any(order_id in item for item in orders_list):
            orders_list.append(order_info)
            new_balance = current_balance + commission
            
            supabase.table('users').update({
                balance_key: new_balance,
                orders_key: orders_list
            }).eq('id', user_id).execute()

            try:
                bot.send_message(
                    user_id, 
                    f"🎉 **GHI NHẬN ĐƠN HÀNG MỚI!**\n\n"
                    f"📦 Mã đơn: `{order_id}`\n"
                    f"💰 Hoa hồng tạm tính: **+{commission:,.0f} VNĐ**\n"
                    f"💳 Số dư ví hiện tại: **{new_balance:,.0f} VNĐ**\n\n"
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
                f"💳 Số dư ví hiện tại: **{new_balance:,.0f} VNĐ**"
            )
        except Exception as e:
            print(f"Lỗi gửi tin nhắn hủy đơn: {e}")

    return "OK", 200

# ==========================================
# 6. CÁC LỆNH ADMIN QUẢN LÝ / CHAT / BROADCAST
# ==========================================
@bot.message_handler(commands=['chat'])
def admin_chat_single(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        bot.reply_to(message, "❌ Bạn không có quyền sử dụng lệnh này!")
        return

    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(
            message, 
            "⚠️ **Cú pháp sai!**\n👉 Dùng: `/chat <telegram_id> <Nội dung tin nhắn>`\n*Ví dụ:* `/chat 8860640969 Chào chị, đơn hàng đã được kiểm tra xong nhé!`", 
            parse_mode="Markdown"
        )
        return

    target_id = parts[1].strip()
    content = parts[2].strip()

    try:
        msg_to_user = (
            f"💬 **TIN NHẮN TỪ HỖ TRỢ KHÁCH HÀNG**\n\n"
            f"{content}"
        )
        bot.send_message(target_id, msg_to_user, parse_mode="Markdown")
        bot.reply_to(message, f"✅ Đã gửi tin nhắn riêng thành công đến ID `{target_id}`!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Không thể gửi tin nhắn cho ID `{target_id}`. Nguyên nhân: {e}", parse_mode="Markdown")

@bot.message_handler(commands=['nhan'])
def admin_chat_broadcast(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        bot.reply_to(message, "❌ Bạn không có quyền sử dụng lệnh này!")
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(
            message, 
            "⚠️ **Cú pháp sai!**\n👉 Dùng: `/nhan <Nội dung thông báo hàng loạt>`\n*Ví dụ:* `/nhan Siêu Sale 11/11: Hoàn tiền gấp đôi cho tất cả đơn Shopee hôm nay!`", 
            parse_mode="Markdown"
        )
        return

    content = parts[1].strip()

    try:
        users_response = supabase.table('users').select('id').execute()
        users = users_response.data or []
    except Exception as e:
        bot.reply_to(message, f"❌ Lỗi truy vấn cơ sở dữ liệu Supabase: {e}")
        return

    if not users:
        bot.reply_to(message, "ℹ️ Hệ thống hiện chưa có người dùng nào để gửi thông báo.")
        return

    bot.reply_to(message, f"⏳ Đang tiến hành gửi thông báo tới {len(users)} người dùng...")

    success_count = 0
    fail_count = 0

    broadcast_msg = (
        f"📢 **THÔNG BÁO TỪ HỆ THỐNG**\n\n"
        f"{content}"
    )

    for u in users:
        uid = u.get('id')
        if not uid:
            continue
        try:
            bot.send_message(uid, broadcast_msg, parse_mode="Markdown")
            success_count += 1
        except Exception:
            fail_count += 1

    bot.reply_to(
        message, 
        f"🎉 **ĐÃ HOÀN TẤT GỬI THÔNG BÁO HÀNG LOẠT!**\n\n"
        f"✅ Thành công: **{success_count}** người dùng\n"
        f"❌ Thất bại (Do chặn bot/lỗi): **{fail_count}** người dùng", 
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda message: str(message.from_user.id) != str(ADMIN_ID) and not (message.text and message.text.startswith('/')))
def forward_to_admin(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Khách hàng"
    
    if message.text:
        notification_text = (
            f"📩 **CÓ YÊU CẦU/TIN NHẮN MỚI TỪ KHÁCH HÀNG!**\n\n"
            f"👤 **Khách:** {user_name}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"💬 **Nội dung:**\n{message.text}\n\n"
            f"👉 *Trả lời nhanh:* `/chat {user_id} <nội dung>`"
        )
        bot.send_message(ADMIN_ID, notification_text, parse_mode="Markdown")
        
    elif message.photo:
        notification_text = (
            f"📷 **KHÁCH GỬI HÌNH ẢNH (STK/GÓP Ý)!**\n\n"
            f"👤 **Khách:** {user_name}\n"
            f"🆔 **ID:** `{user_id}`\n\n"
            f"👉 *Trả lời nhanh:* `/chat {user_id} <nội dung>`"
        )
        bot.send_message(ADMIN_ID, notification_text, parse_mode="Markdown")
        
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
