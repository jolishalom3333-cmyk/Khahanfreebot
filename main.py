import os
import re
import json
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

# ==========================================
# 1. CẤU HÌNH BIẾN MÔI TRƯỜNG & KHỞI TẠO
# ==========================================
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()

SHOPEE_AFFILIATE_ID = os.environ.get('SHOPEE_AFFILIATE_ID', '17317720169').strip()
RIOHUB_API_KEY = os.environ.get('RIOHUB_API_KEY', '').strip()

# 👉 BỔ SUNG: Thêm biến lấy Shopee API Key chuẩn xác 2026
SHOPEE_API_KEY = os.environ.get('SHOPEE_API_KEY', '99ba514854ed2fdf9b68b6a913aa8192a1021272ee82f639').strip()

CASHBACK_RATE = float(os.environ.get('CASHBACK_PERCENT', 70)) / 100.0
CREATOR_USERNAME = os.environ.get('CREATOR_USERNAME', 'thaonguyen2002').strip()

RIOHUB_BASE_URLS = [
    "https://riohub.vn/api/v1",
    "https://riohub.riokupon.com/api/v1",
    "https://riohub.riokupon.me/api/v1"
]

app = Flask(__name__)
CORS(app) # 👈 Đã thêm CORS để website gọi sang không bị chặn

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
# 3. HÀM XỬ LÝ CHUYỂN ĐỔI LINK TIKTOK (RIOHUB)
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

# ==========================================
# 4. HÀM XỬ LÝ CHUYỂN ĐỔI LINK SHOPEE (AN_REDIR CHUẨN)
# ==========================================
def clean_shopee_url(raw_url: str) -> str:
    target_url = raw_url.strip()
    if any(domain in target_url.lower() for domain in ["s.shopee.vn", "shp.ee", "shope.ee"]):
        try:
            r = requests.head(target_url, allow_redirects=True, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            target_url = r.url
        except Exception:
            try:
                r = requests.get(target_url, allow_redirects=True, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                target_url = r.url
            except Exception:
                pass

    parsed = urlparse(target_url)
    netloc = parsed.netloc if parsed.netloc else "shopee.vn"
    clean_url = f"https://{netloc}{parsed.path}"
    return clean_url

def convert_shopee_link(original_url: str, user_id: str) -> str:
    try:
        if not SHOPEE_AFFILIATE_ID:
            print("❌ Thiếu SHOPEE_AFFILIATE_ID!")
            return None

        clean_landing_page = clean_shopee_url(original_url)
        encoded_landing = quote(clean_landing_page, safe='')
        formatted_sub_id = f"joli-{user_id}"
        
        affiliate_link = (
            f"https://s.shopee.vn/an_redir"
            f"?origin_link={encoded_landing}"
            f"&affiliate_id={SHOPEE_AFFILIATE_ID}"
            f"&sub_id={formatted_sub_id}"
        )
        return affiliate_link
    except Exception as e:
        print(f"❌ Lỗi tạo link Shopee an_redir: {e}")
        return None

# ==========================================
# 4.1 BỔ SUNG: HÀM ĐỒNG BỘ ĐƠN HÀNG SHOPEE TỪ ADDLIVETAG
# ==========================================
def sync_shopee_orders():
    if not supabase or not SHOPEE_API_KEY:
        return
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        past_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        url = f"https://addlivetag.com/api/v1/conversions.php?api_key={SHOPEE_API_KEY}&type=items&from={past_date}&to={today}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            orders = data.get('data', []) or data.get('items', []) or []
            for item in orders:
                order_id = str(item.get('order_id') or item.get('order_sn', '')).strip()
                sub_id = str(item.get('sub_id', '')).strip()
                commission_goc = float(item.get('commission') or item.get('estimated_commission', 0))
                status = str(item.get('status', 'pending')).strip()

                if order_id and sub_id and "joli-" in sub_id:
                    user_id = sub_id.replace("joli-", "").strip()
                    thuc_nhan = commission_goc * 0.6
                    supabase.table('transactions').upsert({
                        "order_id": order_id,
                        "user_id": user_id,
                        "commission_goc": commission_goc,
                        "thuc_nhan": thuc_nhan,
                        "status": status,
                        "updated_at": datetime.now().isoformat()
                    }, on_conflict="order_id").execute()
    except Exception as e:
        print(f"Lỗi đồng bộ Shopee: {e}")

# ==========================================
# 5. API CHÍNH CHO WEBSITE (DÁN LINK TRỰC TIẾP)
# ==========================================
@app.route('/api/convert', methods=['POST'])
def web_convert_link():
    try:
        data = request.get_json(silent=True) or {}
        raw_url = data.get('url', '').strip()
        user_id = data.get('user_id', 'web_guest').strip()

        if not raw_url:
            return jsonify({"success": False, "error": "Vui lòng nhập đường dẫn sản phẩm!"}), 400

        log_click(user_id, raw_url)
        
        afflink = None
        platform = ""

        if "tiktok" in raw_url.lower():
            platform = "TikTok Shop"
            afflink, err_msg = createAffiliateLink(raw_url, user_id)
            if not afflink:
                return jsonify({"success": False, "error": f"Lỗi TikTok: {err_msg or 'Không thể tạo link qua RioHub.'}"}), 400

        elif any(d in raw_url.lower() for d in ["shopee", "shp.ee", "shope.ee"]):
            platform = "Shopee"
            afflink = convert_shopee_link(raw_url, user_id)
            if not afflink:
                return jsonify({"success": False, "error": "Lỗi Shopee: Không thể khởi tạo link mua hàng."}), 400
        else:
            return jsonify({"success": False, "error": "Hệ thống chỉ hỗ trợ tạo link cho Shopee và TikTok Shop!"}), 400

        return jsonify({
            "success": True,
            "platform": platform,
            "affiliate_link": afflink
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"Lỗi hệ thống: {str(e)} "}), 500

# ==========================================
# 6. API NHẬN WEBHOOK / POSTBACK TỪ RIOHUB (GIỮ NGUYÊN)
# ==========================================
@app.route('/api/riohub-webhook', methods=['POST'])
def riohub_webhook():
    try:
        data = request.get_json(silent=True) or {}
        
        sub_id = str(data.get('sub_id', '')).strip() 
        order_id = str(data.get('order_id', '')).strip()
        commission_goc = float(data.get('commission', 0)) 
        status = str(data.get('status', 'pending')).strip() 

        if not sub_id or not order_id:
            return jsonify({"success": False, "error": "Thiếu sub_id hoặc order_id"}), 400

        user_id = sub_id.replace("joli-", "").strip()
        thuc_nhan = commission_goc * 0.6

        if supabase:
            supabase.table('transactions').upsert({
                "order_id": order_id,
                "user_id": user_id,
                "commission_goc": commission_goc,
                "thuc_nhan": thuc_nhan,
                "status": status,
                "updated_at": datetime.now().isoformat()
            }, on_conflict="order_id").execute()

        return jsonify({"success": True, "message": "Đã đồng bộ đơn hàng về Supabase thành công!"}), 200

    except Exception as e:
        return jsonify({"success": False, "error": f"Lỗi webhook: {str(e)}"}), 500

# ==========================================
# 6.1 BỔ SUNG: API KÍCH HOẠT QUÉT ĐƠN SHOPEE THỦ CÔNG/ĐỊNH KỲ
# ==========================================
@app.route('/api/sync-shopee', methods=['GET', 'POST'])
def trigger_sync_shopee():
    try:
        sync_shopee_orders()
        return jsonify({"success": True, "message": "Đã quét và đồng bộ đơn hàng Shopee thành công!"}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Joli Affiliate Server is Running!", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    
