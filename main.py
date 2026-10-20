import os
import hmac
import hashlib
import json
import threading
import time
from datetime import datetime
from urllib.parse import quote
from flask import Flask, request
import requests
import telebot

# --- 1. CẤU HÌNH BIẾN MÔI TRƯỜNG ---
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID') or "8860640969"
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()

# Biến môi trường RioHub & Accesstrade
RIOHUB_API_KEY = os.environ.get('RIOHUB_API_KEY', '').strip()
RIOHUB_SIGNING_SECRET = os.environ.get('RIOHUB_SIGNING_SECRET', '').strip()

# Tỷ lệ hoàn tiền cho khách (Mặc định 90% -> Admin hưởng 10%)
CASHBACK_RATE = float(os.environ.get('CASHBACK_PERCENT', 90)) / 100.0

bot = telebot.TeleBot(TOKEN) if TOKEN else None
app = Flask(__name__)

# Kết nối CSDL Supabase
supabase_error = ""
supabase = None

if not SUPABASE_URL:
    supabase_error = "Thiếu SUPABASE_URL trên Render Environment"
elif not SUPABASE_KEY:
    supabase_error = "Thiếu SUPABASE_KEY trên Render Environment"
else:
    try:
        from supabase import create_client
        clean_url = SUPABASE_URL.strip("[]'\" ")
        clean_key = SUPABASE_KEY.strip("[]'\" ")
        supabase = create_client(clean_url, clean_key)
        print("✅ Kết nối Supabase thành công!")
    except Exception as e:
        supabase_error = f"Lỗi khởi tạo Supabase: {str(e)}"
        print(f"❌ {supabase_error}")


# --- 2. HÀM TƯƠNG TÁC CƠ SỞ DỮ LIỆU SUPABASE ---
def get_user(user_id):
    if not supabase:
        return None
    try:
        res = supabase.table('users').select('*').eq('id', str(user_id)).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print("Lỗi đọc dữ liệu user Supabase:", e)
    return None

def save_or_update_user(user_id, name=None, username=None, balance=None, orders=None):
    if not supabase:
        return
    try:
        user_id_str = str(user_id)
        existing = get_user(user_id_str)
        
        if existing:
            data_to_update = {}
            if name is not None: data_to_update["name"] = name
            if username is not None: data_to_update["username"] = username
            if balance is not None: data_to_update["balance"] = balance
            if orders is not None: data_to_update["orders"] = orders
            
            if data_to_update:
                supabase.table('users').update(data_to_update).eq('id', user_id_str).execute()
        else:
            new_data = {
                "id": user_id_str,
                "name": name or "Khách hàng",
                "username": username or "",
                "balance": balance if balance is not None else 0,
                "orders": orders if orders is not None else []
            }
            supabase.table('users').insert(new_data).execute()
    except Exception as e:
        print("Lỗi ghi dữ liệu user Supabase:", e)

def log_click(user_id, raw_url):
    """Ghi nhận thông tin click vào bảng clicks trên Supabase"""
    if not supabase:
        return
    try:
        click_data = {
            "user_id": str(user_id),
            "original_url": raw_url,
            "created_at": datetime.now().isoformat()
        }
        supabase.table('clicks').insert(click_data).execute()
    except Exception as e:
        print("Lưu thông tin Click gặp sự cố:", e)


# --- 3. HÀM CHUYỂN ĐỔI LINK RIOHUB (TIKTOK SHOP) ---
def convert_link_riohub(original_url, user_id):
    """Gọi API RioHub để lấy link affiliate TikTok Shop kèm sub_id=user_id"""
    if not RIOHUB_API_KEY:
        print("⚠️ Chưa cài RIOHUB_API_KEY trên Render Environment!")
        return None

    endpoint = "https://riohub.vn/api/v1/partner/tiktok/affiliate/links"
    headers = {
        "X-Riohub-Api-Key": RIOHUB_API_KEY.strip(),
        "Content-Type": "application/json"
    }
    payload = {
        "product_url": original_url,
        "sub_id": str(user_id)
    }

    try:
        res = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        print("🔎 [RioHub API Code]:", res.status_code)
        print("🔎 [RioHub API Response]:", res.text)
        
        if res.status_code == 200:
            res_data = res.json()
            # Bóc tách link linh hoạt theo cấu trúc trả về của RioHub
            link = (
                res_data.get("affiliate_link") or 
                res_data.get("link") or 
                res_data.get("data", {}).get("affiliate_link") or 
                res_data.get("data", {}).get("link")
            )
            if link:
                return link
            print("❌ RioHub trả về 200 nhưng không tìm thấy key affiliate_link!")
        else:
            print(f"❌ Lỗi gọi API RioHub HTTP {res.status_code}: {res.text}")
    except Exception as e:
        print("❌ Sự cố kết nối API RioHub:", e)

    return None


# --- 4. CÁC CÂU LỆNH TELEGRAM BOT ---
if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        uid = str(message.chat.id)
        first_name = message.from_user.first_name or "Khách"
        username = message.from_user.username or ""

        user = get_user(uid)
        if not user:
            save_or_update_user(uid, name=first_name, username=username, balance=0, orders=[])
        else:
            save_or_update_user(uid, name=first_name, username=username)

        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("📦 Đơn hàng của tôi", "💳 Ví & Số dư")
        markup.add("❓ Hướng dẫn mua hàng", "💬 Hỗ trợ Admin")
        
        welcome_text = (
            f"👋 **Chào mừng {first_name} đến với Bot Hoàn Tiền Tự Động!**\n\n"
            f"🛒 **Cách nhận hoàn tiền {int(CASHBACK_RATE * 100)}%:**\n"
            f"1️⃣ Copy link sản phẩm trên Shopee / TikTok Shop.\n"
            f"2️⃣ Gửi link trực tiếp vào đây cho Bot.\n"
            f"3️⃣ Bấm link rút gọn Bot trả về để tiến hành thanh toán mua hàng.\n\n"
            f"📌 *Bấm '❓ Hướng dẫn mua hàng' bên dưới để biết cách mua không bị mất đơn!*"
        )
        bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text == "📦 Đơn hàng của tôi")
    def my_orders(message):
        uid = str(message.from_user.id)
        user = get_user(uid)
        orders = user.get("orders", []) if user else []
        if not orders:
            bot.reply_to(message, "📦 Bạn chưa có đơn hàng nào được ghi nhận.")
        else:
            recent = orders[-10:]
            msg_text = "📦 **LỊCH SỬ ĐƠN HÀNG GẦN ĐÂY:**\n\n" + "\n".join([f"• {item}" for item in recent])
            bot.reply_to(message, msg_text, parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text == "💳 Ví & Số dư")
    def my_balance(message):
        uid = str(message.from_user.id)
        user = get_user(uid)
        bal = user.get("balance", 0) if user else 0
        bot.reply_to(
            message, 
            f"💳 **SỐ DƯ VÍ TÍCH LŨY:** `{bal:,.0f} VNĐ`\n\n"
            f"💡 *Khi đạt hạn mức rút tiền, nhắn Admin qua nút '💬 Hỗ trợ Admin' để được duyệt thanh toán khoản cashback nhé!*", 
            parse_mode="Markdown"
        )

    @bot.message_handler(func=lambda msg: msg.text in ["❓ Hướng dẫn mua hàng", "/huongdan"])
    def shopping_guide(message):
        guide_text = (
            "📌 **QUY TRÌNH MUA HÀNG ĐỂ ĐẢM BẢO NHẬN ĐỦ HOÀN TIỀN:**\n\n"
            "1️⃣ **Không bỏ sẵn hàng vào giỏ:** Xóa sản phẩm khỏi giỏ trước khi lấy link qua Bot.\n"
            "2️⃣ **Thao tác liền mạch:** Copy link gửi Bot ➔ Bấm link Bot trả về ➔ Thêm vào giỏ và Thanh toán ngay.\n"
            "3️⃣ **1 Link = 1 Đơn:** Mỗi lần muốn mua đơn mới, vui lòng gửi lại link cho Bot lấy link tracking mới.\n"
            "4️⃣ **Thời gian ghi nhận đơn:**\n"
            "   • **TikTok Shop:** Cập nhật sau 1-3 giờ.\n"
            "   • **Shopee:** Cập nhật sau 24h - 48h (không tính đơn hủy/trả).\n\n"
            "🎯 *Chúc bạn mua sắm tiết kiệm nhất!*"
        )
        bot.reply_to(message, guide_text, parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text == "💬 Hỗ trợ Admin")
    def contact_admin(message):
        bot.reply_to(
            message, 
            "💬 Bạn cần hỗ trợ hoặc rút tiền hoàn? Hãy gửi tin nhắn chi tiết kèm **Mã đơn hàng/SĐT** vào đây, Admin sẽ hỗ trợ xử lý trực tiếp nhé!",
            parse_mode="Markdown"
        )

    @bot.message_handler(func=lambda msg: msg.text is not None and msg.text.startswith("http"))
    def convert_link(message):
        uid = message.from_user.id
        raw_url = message.text.strip()
        
        # Ghi nhận Click đếm CVR
        log_click(uid, raw_url)
        
        # PHÂN LOẠI TIKTOK SHOP (RIOHUB) HOẶC SHOPEE (ACCESSTRADE)
        if "tiktok" in raw_url.lower():
            afflink = convert_link_riohub(raw_url, uid)
            # Dự phòng nếu API RioHub chưa hoạt động/lỗi thì mới fallback sang Accesstrade
            if not afflink:
                encoded_url = quote(raw_url, safe='')
                campaign_path = "7073909970291373175/6648523843406889655"
                afflink = f"https://go.isclix.com/deep_link/{campaign_path}?url={encoded_url}&sub_id={uid}"
        else:
            encoded_url = quote(raw_url, safe='')
            campaign_path = "7073909970291373175/4751584435713464237"  # Shopee
            afflink = f"https://go.isclix.com/deep_link/{campaign_path}?url={encoded_url}&sub4=oneatweb&sub_id={uid}"
        
        bot.reply_to(
            message, 
            f"🛍️ <a href='{afflink}'><b>LINK MUA HÀNG HOÀN TIỀN {int(CASHBACK_RATE*100)}%</b></a>\n\n"
            f"👉 <a href='{afflink}'>BẤM VÀO ĐÂY ĐỂ MUA HÀNG</a>\n\n"
            f"⚠️ <i>Lưu ý: Không bỏ sản phẩm sẵn vào giỏ trước khi bấm link nhé!</i>", 
            parse_mode="HTML"
        )

    # --- HỆ THỐNG LỆNH ADMIN (BOSS QUẢN LÝ) ---
    @bot.message_handler(commands=['baocao', 'stats'])
    def view_report(message):
        if str(message.from_user.id) != str(ADMIN_ID): return
        if not supabase:
            bot.reply_to(message, "❌ Chưa kết nối CSDL Supabase!")
            return

        try:
            click_res = supabase.table('clicks').select('id', count='exact').execute()
            total_clicks = click_res.count if click_res.count is not None else 0

            user_res = supabase.table('users').select('*').execute()
            users = user_res.data or []
            
            total_users = len(users)
            total_cashback_given = sum([u.get('balance', 0) for u in users])
            admin_profit_est = (total_cashback_given / CASHBACK_RATE) * (1.0 - CASHBACK_RATE) if CASHBACK_RATE > 0 else 0
            cvr = (total_users / total_clicks * 100) if total_clicks > 0 else 0

            report_msg = (
                "📊 **BÁO CÁO HIỆU SUẤT VẬN HÀNH BOT**\n"
                "------------------------------------\n"
                f"👤 **Tổng số Khách hàng:** `{total_users}` người\n"
                f"🖱️ **Tổng số Lượt Click:** `{total_clicks}` clicks\n"
                f"📈 **Tỷ lệ chuyển đổi (CVR ước tính):** `{cvr:.2f}%` \n"
                "------------------------------------\n"
                f"💰 **Tổng Cashback chờ trả khách ({int(CASHBACK_RATE*100)}%):** `{total_cashback_given:,.0f} VNĐ`\n"
                f"💵 **Lợi nhuận Admin tích lũy ({int((1-CASHBACK_RATE)*100)}%):** `{admin_profit_est:,.0f} VNĐ`\n"
                "------------------------------------\n"
                "📌 *Gõ `/danhsach` để xem chi tiết từng người dùng.*"
            )
            bot.reply_to(message, report_msg, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, f"❌ Lỗi lấy báo cáo: {str(e)}")

    @bot.message_handler(commands=['congtien'])
    def cong_tien(message):
        if str(message.from_user.id) != str(ADMIN_ID): return
        try:
            parts = message.text.split()
            target_id = parts[1]
            amount = int(parts[2])
            
            user = get_user(target_id)
            old_bal = user.get("balance", 0) if user else 0
            old_orders = user.get("orders", []) if user else []
            
            new_bal = old_bal + amount
            order_entry = f"➕ Admin cộng tay: +{amount:,.0f} VNĐ"
            old_orders.append(order_entry)
            
            save_or_update_user(target_id, balance=new_bal, orders=old_orders)
            bot.reply_to(message, f"✅ Đã cộng {amount:,.0f} VNĐ cho ID `{target_id}`", parse_mode="Markdown")
            try:
                bot.send_message(target_id, f"🎉 Bạn vừa được Admin cộng +{amount:,.0f} VNĐ vào ví tích lũy!")
            except Exception:
                pass
        except Exception:
            bot.reply_to(message, "⚠️ Cú pháp: `/congtien <USER_ID> <SO_TIEN>`", parse_mode="Markdown")

    @bot.message_handler(commands=['thanhtoan'])
    def thanh_toan(message):
        if str(message.from_user.id) != str(ADMIN_ID): return
        try:
            parts = message.text.split(maxsplit=2)
            target_id = parts[1]
            note = parts[2] if len(parts) > 2 else "Thanh toán hoa hồng kỳ này"
            
            user = get_user(target_id)
            if not user:
                bot.reply_to(message, "❌ Không tìm thấy người dùng này!")
                return
                
            old_bal = user.get("balance", 0)
            save_or_update_user(target_id, balance=0, orders=[])
            
            bot.reply_to(message, f"✅ **Đã thanh toán & Reset về 0đ**\n👤 ID: `{target_id}`\n💵 Tiền: {old_bal:,.0f} VNĐ\n📝 Ghi chú: {note}", parse_mode="Markdown")
            try:
                bot.send_message(
                    target_id,
                    f"🎉 **THÔNG BÁO TẤT TOÁN HOA HỒNG**\n\n💰 Số tiền chuyển trả: *{old_bal:,.0f} VNĐ*\n📝 Nội dung: {note}\n\n🔄 Ví tích lũy đã được reset về 0 VNĐ cho chu kỳ mới.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        except Exception:
            bot.reply_to(message, "⚠️ Cú pháp: `/thanhtoan <USER_ID> [Ghi chú]`", parse_mode="Markdown")

    @bot.message_handler(commands=['danhsach'])
    def list_users(message):
        if str(message.from_user.id) != str(ADMIN_ID): return
        try:
            if not supabase:
                bot.reply_to(message, f"❌ Chưa kết nối Supabase thành công!\n\n👉 <b>Lý do:</b> {supabase_error}", parse_mode="HTML")
                return
            res = supabase.table('users').select('*').execute()
            users = res.data
            if not users:
                bot.reply_to(message, "📂 Chưa có khách hàng nào.")
                return

            msg = f"📋 <b>DANH SÁCH KHÁCH HÀNG & SỐ DƯ ({int(CASHBACK_RATE*100)}%):</b>\n\n"
            for info in users:
                uid = info['id']
                name = info.get("name", "Khách hàng")
                username = f"(@{info['username']})" if info.get("username") else ""
                balance = info.get("balance", 0)
                
                msg += f"👤 <b><a href='tg://user?id={uid}'>{name}</a></b> {username}\n"
                msg += f"🆔 ID: <code>{uid}</code>\n"
                msg += f"💰 Số dư: <b>{balance:,.0f} VNĐ</b>\n"
                msg += f"👉 Nhắn nhanh: <code>/nhan {uid} Nội dung</code>\n"
                msg += "-------------------------------\n"

            bot.send_message(ADMIN_ID, msg, parse_mode="HTML")
        except Exception as e:
            bot.reply_to(message, f"❌ Lỗi: {e}")

    @bot.message_handler(commands=['nhan'])
    def send_custom_msg(message):
        if str(message.from_user.id) != str(ADMIN_ID): return
        try:
            p = message.text.split(" ", 2)
            bot.send_message(p[1], f"💬 **Lời nhắn từ Admin:**\n\n{p[2]}", parse_mode="Markdown")
            bot.reply_to(message, "✅ Đã gửi tin nhắn thành công!")
        except Exception:
            bot.reply_to(message, "⚠️ Cú pháp: `/nhan <ID_KHÁCH> <NỘI_DUNG>`", parse_mode="Markdown")


# --- 5. WEBHOOK NHẬN POSTBACK TỰ ĐỘNG TỪ RIOHUB & ACCESSTRADE ---
@app.route('/', methods=['GET', 'POST', 'HEAD'])
@app.route('/postback', methods=['GET', 'POST', 'HEAD'])
def webhook():
    if request.method == 'HEAD':
        return "", 200

    # --- 5.1. XỬ LÝ DỮ LIỆU TỪ RIOHUB (POST JSON) ---
    if request.is_json or request.method == 'POST':
        try:
            body_bytes = request.get_data()
            data = json.loads(body_bytes.decode('utf-8')) if body_bytes else {}
            
            if data and ("event" in data or "order_id" in data or "commission" in data):
                target_id = str(data.get("sub_id") or data.get("trace_id") or "").strip()
                comm = float(data.get("commission") or data.get("pub_commission") or 0)
                order_id = str(data.get("order_id") or data.get("id") or "Mới")
                event_type = str(data.get("event") or "").lower()

                if target_id and comm > 0 and bot:
                    cashback = int(comm * CASHBACK_RATE)
                    admin_profit = int(comm - cashback)

                    user = get_user(target_id)
                    old_bal = user.get("balance", 0) if user else 0
                    old_orders = user.get("orders", []) if user else []

                    # ĐƠN HỦY / HOÀN TỪ RIOHUB
                    if event_type in ["order.refunded", "cancelled", "rejected"]:
                        new_bal = max(0, old_bal - cashback)
                        old_orders.append(f"❌ Hủy/Hoàn đơn RioHub #{order_id}: -{cashback:,.0f} VNĐ")
                        save_or_update_user(target_id, balance=new_bal, orders=old_orders)

                        try:
                            bot.send_message(
                                target_id,
                                f"⚠️ **CẬP NHẬT: ĐƠN HÀNG RIOHUB BỊ HỦY / TRẢ!**\n\n📦 Mã đơn: `{order_id}`\n🔻 Khấu trừ: **-{cashback:,.0f} VNĐ**",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            pass

                        if ADMIN_ID:
                            try:
                                bot.send_message(
                                    ADMIN_ID,
                                    f"🔻 **BÁO HỦY ĐƠN RIOHUB!**\n👤 ID: `{target_id}` | Mã đơn: `{order_id}`\n🔻 Trừ khách: -{cashback:,.0f} VNĐ",
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                pass

                    # ĐƠN MỚI HOẶC CẬP NHẬT HOA HỒNG THÀNH CÔNG
                    else:
                        new_bal = old_bal + cashback
                        old_orders.append(f"🛒 Hoàn tiền RioHub #{order_id}: +{cashback:,.0f} VNĐ")
                        save_or_update_user(target_id, balance=new_bal, orders=old_orders)

                        try:
                            bot.send_message(
                                target_id,
                                f"🎉 **ĐƠN HÀNG TIKTOK SHOP ĐƯỢC GHI NHẬN!**\n\n📦 Mã đơn: `{order_id}`\n💰 Bạn được cộng **+{cashback:,.0f} VNĐ** vào ví!",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            pass

                        if ADMIN_ID:
                            try:
                                client_name = user.get("name", "Khách hàng") if user else "Khách hàng"
                                bot.send_message(
                                    ADMIN_ID,
                                    f"🔔 *CÓ ĐƠN TIKTOK SHOP MỚI (RIOHUB)!*\n\n"
                                    f"👤 *Khách:* [{client_name}](tg://user?id={target_id})\n"
                                    f"🆔 ID Khách: `{target_id}`\n📦 Mã đơn: `{order_id}`\n"
                      
