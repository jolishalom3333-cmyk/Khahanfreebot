import os
import re
from urllib.parse import quote
from flask import Flask, request, jsonify
import requests
import telebot

# --- 1. CẤU HÌNH BIẾN MÔI TRƯỜNG ---
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN') or ""
TOKEN = TOKEN.strip("[]'\" ")

ADMIN_ID = os.environ.get('ADMIN_ID', '8860640969').strip("[]'\" ")
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip("[]'\" ")
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip("[]'\" ")

RIOHUB_API_KEY = os.environ.get('RIOHUB_API_KEY', '').strip("[]'\" ")
RIOHUB_SIGNING_SECRET = os.environ.get('RIOHUB_SIGNING_SECRET', '').strip("[]'\" ")
TIKTOK_CREATOR = os.environ.get('TIKTOK_CREATOR', 'pheejzoo1564').strip("[]'\" ")

bot = telebot.TeleBot(TOKEN) if TOKEN else None
app = Flask(__name__)

# --- TỰ ĐỘNG CÀI ĐẶT WEBHOOK CHO TELEGRAM BOT ---
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL', '').strip("[]'\" ")
if not RENDER_EXTERNAL_URL:
    RENDER_EXTERNAL_URL = "https://khahanfreebot.onrender.com"

if bot and TOKEN:
    try:
        webhook_url = f"{RENDER_EXTERNAL_URL}/telegram-webhook"
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        print(f"✅ Đã kích hoạt Telegram Webhook: {webhook_url}")
    except Exception as e:
        print(f"⚠️ Cảnh báo thiết lập Webhook Telegram: {e}")

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
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Kết nối Supabase thành công!")
    except Exception as e:
        supabase_error = f"Lỗi khởi tạo Supabase: {str(e)}"
        print(f"❌ {supabase_error}")

# --- HÀM TẠO LINK TIKTOK BẰNG RIOHUB API ---
def create_riohub_tiktok_link(raw_text, user_id):
    url_match = re.search(r'https?://[^\s]+', raw_text)
    if not url_match:
        return None
    clean_url = url_match.group(0)

    api_key = RIOHUB_API_KEY or "rhk_567d9c91872f7dacbd60bad98e282caf17d83f81cc513a1a"

    headers = {
        "X-Riohub-Api-Key": api_key,
        "X-API-KEY": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    endpoints = [
        ("https://riohub.vn/api/v1/partner/tiktok/affiliate/links", {
            "creator_username": TIKTOK_CREATOR,
            "product_url": clean_url,
            "sub_id": str(user_id)
        }),
        ("https://riohub.vn/api/v1/partner/tiktok/affiliate/links", {
            "product_url": clean_url,
            "sub_id": str(user_id)
        }),
        ("https://api.riohub.vn/v1/tools/convert-link", {
            "url": clean_url,
            "sub_id": str(user_id)
        })
    ]

    for ep_url, payload in endpoints:
        try:
            res = requests.post(ep_url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                link = data.get("affiliate_link") or data.get("short_link") or data.get("url")
                if not link and isinstance(data.get("data"), dict):
                    link = data["data"].get("affiliate_link") or data["data"].get("short_link") or data["data"].get("url")
                if link:
                    return link
            else:
                print(f"❌ API RioHub Error {res.status_code} ({ep_url}): {res.text}")
        except Exception as e:
            print(f"❌ Lỗi kết nối RioHub ({ep_url}): {e}")

    return None

# --- 2. HÀM ĐỌC / GHI DỮ LIỆU TỪ SUPABASE ---
def get_user(user_id):
    if not supabase:
        return None
    try:
        res = supabase.table('users').select('*').eq('id', str(user_id)).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print("Lỗi đọc dữ liệu Supabase:", e)
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
        print("Lỗi ghi dữ liệu Supabase:", e)

# --- 3. CỔNG NHẬN TIN NHẮN TELEGRAM QUA WEBHOOK ---
@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
    if not bot:
        return "Bot non-initialized", 500
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return '', 200
        return 'Invalid content-type', 400
    except Exception as e:
        print(f"❌ Lỗi xử lý Telegram Webhook: {e}")
        return 'Error', 500

# --- CÁC HÀM XỬ LÝ LỆNH BOT ---
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
        bot.reply_to(message, f"👋 Chào mừng {first_name}! Hãy gửi link Shopee/TikTok để mua hàng hoàn tiền.", reply_markup=markup)

    @bot.message_handler(func=lambda msg: msg.text == "📦 Đơn hàng của tôi")
    def my_orders(message):
        uid = str(message.from_user.id)
        user = get_user(uid)
        orders = user.get("orders", []) if user else []
        if not orders:
            bot.reply_to(message, "📦 Bạn chưa có đơn hàng nào được ghi nhận.")
        else:
            recent = orders[-10:]
            msg_text = "📦 **LỊCH SỬ ĐƠN HÀNG:**\n\n" + "\n".join([f"• {item}" for item in recent])
            bot.reply_to(message, msg_text, parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text == "💳 Ví & Số dư")
    def my_balance(message):
        uid = str(message.from_user.id)
        user = get_user(uid)
        bal = user.get("balance", 0) if user else 0
        bot.reply_to(message, f"💳 **Số dư tích lũy:** {bal:,.0f} VNĐ", parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.text is not None and "http" in msg.text)
    def convert_link(message):
        uid = message.from_user.id
        raw_text = message.text.strip()
        
        url_match = re.search(r'https?://[^\s]+', raw_text)
        clean_url = url_match.group(0) if url_match else raw_text

        if "tiktok" in clean_url.lower():
            rio_link = create_riohub_tiktok_link(raw_text, uid)
            if rio_link:
                bot.reply_to(
                    message, 
                    f"🎵 <a href='{rio_link}'><b>LINK TIKTOK SHOP HOÀN TIỀN 90%</b></a>\n\n👉 <a href='{rio_link}'>BẤM VÀO ĐÂY ĐỂ MUA HÀNG</a>", 
                    parse_mode="HTML"
                )
            else:
                bot.reply_to(message, "❌ Tạo link TikTok thất bại. Vui lòng kiểm tra lại đường dẫn sản phẩm!")
        else:
            encoded_url = quote(clean_url, safe='')
            merchant = "shopee"
            link_adpia = f"https://click.adpia.vn/tracking.php?m={merchant}&a=A100156876&l=9999&tu={encoded_url}&utm_source={uid}"
            bot.reply_to(
                message, 
                f"🛍️ <a href='{link_adpia}'><b>LINK SHOPEE HOÀN TIỀN 90%</b></a>\n\n👉 <a href='{link_adpia}'>BẤM VÀO ĐÂY ĐỂ MUA HÀNG</a>", 
                parse_mode="HTML"
            )

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
            bot.reply_to(message, f"✅ Đã cộng {amount:,.0f} VNĐ cho ID {target_id}")
            try:
                bot.send_message(target_id, f"🎉 Bạn vừa được Admin cộng +{amount:,.0f} VNĐ vào ví tích lũy!")
            except Exception:
                pass
        except Exception:
            bot.reply_to(message, "⚠️ Cú pháp: `/congtien <USER_ID> <SO_TIEN>`", parse_mode="Markdown")

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

            msg = "📋 <b>DANH SÁCH KHÁCH HÀNG & SỐ DƯ (90%):</b>\n\n"
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

# --- 4. WEBHOOK NHẬN ĐƠN HÀNG HOÀN TIỀN TỪ ADPIA (SHOPEE) ---
@app.route('/', methods=['GET', 'POST', 'HEAD'])
@app.route('/postback', methods=['GET', 'POST', 'HEAD'])
def webhook():
    if request.method == 'HEAD':
        return "", 200

    target_id = request.args.get('sub_id') or request.args.get('subid') or request.args.get('utm_source')
    comm_str = request.args.get('commission') or request.args.get('comm') or request.args.get('money')
    status = request.args.get('status') or request.args.get('state') or 'success'
    order_id = request.args.get('order_id') or request.args.get('order_code') or 'Mới'

    if not target_id and not comm_str:
        return "Bot đang chạy bình thường!", 200

    if target_id and comm_str and bot:
        try:
            target_id = str(target_id).strip()
            total_comm = float(comm_str)
            cashback = int(total_comm * 0.90)
            admin_profit = int(total_comm - cashback)
            status_clean = str(status).lower().strip()

            user = get_user(target_id)
            old_bal = user.get("balance", 0) if user else 0
            old_orders = user.get("orders", []) if user else []

            if status_clean in ["cancel", "cancelled", "0", "reject", "rejected"]:
                new_bal = max(0, old_bal - cashback)
                old_orders.append(f"❌ Shopee Hủy/Hoàn #{order_id}: -{cashback:,.0f} VNĐ")
                save_or_update_user(target_id, balance=new_bal, orders=old_orders)

                try:
                    bot.send_message(
                        target_id,
                        f"⚠️ **CẬP NHẬT SHOPEE: ĐƠN HÀNG BỊ HỦY / TRẢ HÀNG!**\n\n"
                        f"📦 Mã đơn: `{order_id}`\n"
                        f"🔻 Khấu trừ: **-{cashback:,.0f} VNĐ** khỏi ví tích lũy.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Lỗi gửi tin nhắn khách: {e}")

                if ADMIN_ID:
                    try:
                        bot.send_message(
                            ADMIN_ID,
                            f"🔻 **SHOPEE (ADPIA) - ĐƠN HÀNG BỊ HỦY!**\n\n"
                            f"👤 ID Khách: `{target_id}`\n"
                            f"📦 Mã đơn: `{order_id}`\n"
                            f"🔻 Trừ hoàn khách (90%): -{cashback:,.0f} VNĐ\n"
                            f"🔻 Lợi nhuận Admin giảm (10%): -{admin_profit:,.0f} VNĐ",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"Lỗi gửi tin nhắn Admin: {e}")
            else:
                new_bal = old_bal + cashback
                old_orders.append(f"🛒 Shopee Hoàn tiền #{order_id}: +{cashback:,.0f} VNĐ")
                save_or_update_user(target_id, balance=new_bal, orders=old_orders)

                try:
                    bot.send_message(
                        target_id, 
                        f"🎉 **ĐƠN HÀNG SHOPEE MỚI ĐƯỢC GHI NHẬN!**\n\n"
                        f"📦 Mã đơn: `{order_id}`\n"
                        f"💰 Bạn được cộng **+{cashback:,.0f} VNĐ** (90% hoa hồng) vào ví tích lũy!",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Lỗi gửi tin nhắn khách: {e}")

                if ADMIN_ID:
                    try:
                        client_name = user.get("name", "Khách hàng") if user else "Khách hàng"
                        client_link = f"tg://user?id={target_id}"

                        bot.send_message(
                            ADMIN_ID,
                            f"🔔 *CÓ ĐƠN HÀNG SHOPEE MỚI (ADPIA)!*\n\n"
                            f"👤 *Khách hàng:* [{client_name}]({client_link})\n"
                            f"🆔 ID Khách: `{target_id}`\n"
                            f"📦 Mã đơn: `{order_id}`\n"
                            f"💰 Hoa hồng Adpia: {int(total_comm):,} VNĐ\n"
                            f"🎁 Hoàn cho khách (90%): +{cashback:,.0f} VNĐ\n"
                            f"💵 Lợi nhuận Admin (10%): +{admin_profit:,.0f} VNĐ",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"Lỗi gửi tin nhắn Admin: {e}")

        except Exception as e:
            print(f"Lỗi xử lý Postback Shopee: {e}")

    return "OK", 200

# --- 5. WEBHOOK NHẬN ĐƠN HÀNG HOÀN TIỀN TỪ RIOHUB (TIKTOK) ---
@app.route('/tiktok-postback', methods=['GET', 'POST', 'HEAD'])
def tiktok_webhook():
    if request.method == 'HEAD' or request.method == 'GET':
        return "RioHub TikTok Webhook Endpoint đang hoạt động!", 200

    try:
        payload = request.get_json(silent=True) or {}
        event = payload.get("event", "order.created")
        order_info = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        target_id = order_info.get("sub_id") or order_info.get("subid") or order_info.get("utm_source") or payload.get("sub_id")
        comm_val = order_info.get("commission") or order_info.get("publisher_commission") or order_info.get("estimated_commission") or 0
        order_id = order_info.get("order_id") or order_info.get("order_sn") or order_info.get("order_code") or "Mới"
        product_name = order_info.get("product_name") or order_info.get("item_name") or "Sản phẩm TikTok"

        if not target_id:
            return jsonify({"status": "ignored", "reason": "No sub_id"}), 200

        target_id = str(target_id).strip()
        total_comm = float(comm_val)
        cashback = int(total_comm * 0.90)
        admin_profit = int(total_comm - cashback)

        user = get_user(target_id)
        old_bal = user.get("balance", 0) if user else 0
        old_orders = user.get("orders", []) if user else []

        if event in ["order.refunded", "order.cancelled", "cancelled", "refunded"]:
            new_bal = max(0, old_bal - cashback)
            old_orders.append(f"❌ TikTok Hủy/Hoàn #{order_id}: -{cashback:,.0f} VNĐ")
            save_or_update_user(target_id, balance=new_bal, orders=old_orders)

            if bot:
                try:
                    bot.send_message(
                        target_id,
                        f"⚠️ **CẬP NHẬT TIKTOK: ĐƠN HÀNG BỊ HỦY / HOÀN TRẢ!**\n\n"
                        f"📦 Sản phẩm: {product_name}\n"
                        f"🏷 Mã đơn: `{order_id}`\n"
                        f"🔻 Khấu trừ khỏi ví tích lũy: **-{cashback:,.0f} VNĐ**",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Lỗi gửi tin nhắn khách: {e}")

                if ADMIN_ID:
                    try:
                        bot.send_message(
                            ADMIN_ID,
                            f"🔻 **TIKTOK (RIOHUB) - ĐƠN HÀNG BỊ HỦY!**\n\n"
                            f"👤 ID Khách: `{target_id}`\n"
                            f"📦 Mã đơn: `{order_id}`\n"
                            f"🔻 Khấu trừ khách (90%): -{cashback:,.0f} VNĐ\n"
                            f"🔻 Giảm lợi nhuận Admin (10%): -{admin_profit:,.0f} VNĐ",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print(f"Lỗi gửi tin nhắn Admin: {e}")
        else:
            new_bal = old_bal + cashback
            old_orders.append(f"🎵 TikTok Hoàn tiền #{order_id}: +{cashback:,.0f} VNĐ")
            save_or_update_user(target_id, balance=new_bal, orders=old_orders)

            if bot:
                try:
                    bot.send_message(
                        target_id,
                        f"🎉 **ĐƠN HÀNG TIKTOK MỚI ĐƯỢC GHI NHẬN!**\n\n"
                        f"📦 Sản phẩm: {product_name}\n"
                        f"🏷 Mã đơn: `{order_id}`\n"
                        f"💰 Bạn được cộng **+{cashback:,.0f} VNĐ** (90% hoa hồng) vào ví tích lũy!",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Lỗi gửi tin nhắn khách: {e}")

                if ADMIN_ID:
                    try:
                        client_name = user.get("name", "Khách hàng") if user else "Khách hàng"
                        client_link = f"
