import os
import re
import json
import math
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
SHOPEE_API_KEY = os.environ.get('SHOPEE_API_KEY', '99ba514854ed2fdf9b68b6a913aa8192a1021272ee82f639').strip()

CASHBACK_RATE = float(os.environ.get('CASHBACK_PERCENT', 70)) / 100.0
CREATOR_USERNAME = os.environ.get('CREATOR_USERNAME', 'thaonguyen2002').strip()

RIOHUB_BASE_URLS = [
    "https://riohub.vn/api/v1",
    "https://riohub.riokupon.com/api/v1",
    "https://riohub.riokupon.me/api/v1"
]

app = Flask(__name__)
CORS(app)

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
def validate_and_clean_sub_id(user_id: str) -> str:
    clean_id = re.sub(r'[^A-Za-z0-9_.-]', '_', str(user_id))
    if not clean_id:
        clean_id = "web_user"
    return clean_id[:128]

def createAffiliateLink(product_url_or_id: str, user_id: str):
    sub_id_str = validate_and_clean_sub_id(user_id)

    if not RIOHUB_API_KEY:
        return None, "Hệ thống chưa cài đặt RIOHUB_API_KEY!"

    target_url = product_url_or_id
    if str(target_url).startswith("http"):
        try:
            r_head = requests.head(target_url, allow_redirects=True, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
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
        formatted_sub_id = validate_and_clean_sub_id(user_id)
        
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
# 4.1 HÀM ĐỒNG BỘ ĐƠN HÀNG SHOPEE TỪ ADDLIVETAG
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

                if order_id and sub_id:
                    thuc_nhan = commission_goc * CASHBACK_RATE
                    supabase.table('transactions').upsert({
                        "order_id": order_id,
                        "user_id": sub_id,
                        "commission_goc": commission_goc,
                        "thuc_nhan": thuc_nhan,
                        "status": status,
                        "updated_at": datetime.now().isoformat()
                    }, on_conflict="order_id").execute()
    except Exception as e:
        print(f"Lỗi đồng bộ Shopee: {e}")

# ==========================================
# 4.2 HÀM LẤY THÔNG TIN SẢN PHẨM SHOPEE
# ==========================================
def get_shopee_product_info(original_url: str):
    if not SHOPEE_API_KEY:
        return {"title": "Sản phẩm Shopee", "image": "", "price": 0, "commission_rate": 5}
    try:
        api_url = f"https://addlivetag.com/api/v1/product.php?api_key={SHOPEE_API_KEY}&url={quote(original_url)}"
        res = requests.get(api_url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return {
                "title": data.get("title") or data.get("name", "Sản phẩm Shopee"),
                "image": data.get("image") or data.get("thumbnail", ""),
                "price": float(data.get("price", 0)),
                "commission_rate": float(data.get("commission_rate", 5))
            }
    except Exception as e:
        print(f"Lỗi lấy thông tin sản phẩm: {e}")
    
    return {
        "title": "Sản phẩm mua sắm qua Shopee Affiliate",
        "image": "",
        "price": 0,
        "commission_rate": 5
    }

# ==========================================
# 5. API CHÍNH CHO WEBSITE (DÁN LINK TRỰC TIẾP)
# ==========================================
@app.route('/api/convert', methods=['POST'])
def web_convert_link():
    try:
        data = request.get_json(silent=True) or {}
        raw_url = data.get('url', '').strip()
        user_id = data.get('user_id', 'web_user').strip()

        if not raw_url:
            return jsonify({"success": False, "error": "Vui lòng nhập đường dẫn sản phẩm!"}), 400

        log_click(user_id, raw_url)
        
        afflink = None
        platform = ""
        prod_info = {"title": "Sản phẩm Affiliate", "image": "", "price": 0}
        cashback_amount = 0

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
            
            prod_info = get_shopee_product_info(raw_url)
            estimated_commission = (prod_info["price"] * prod_info["commission_rate"] / 100) if prod_info["price"] > 0 else 5000
            cashback_amount = int(estimated_commission * CASHBACK_RATE)
        else:
            return jsonify({"success": False, "error": "Hệ thống chỉ hỗ trợ tạo link cho Shopee và TikTok Shop!"}), 400

        return jsonify({
            "success": True,
            "platform": platform,
            "affiliate_link": afflink,
            "product_title": prod_info["title"],
            "product_image": prod_info["image"],
            "product_price": prod_info["price"],
            "cashback_preview": cashback_amount
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"Lỗi hệ thống: {str(e)}"}), 500

# ==========================================
# 6. API NHẬN WEBHOOK / POSTBACK TỪ RIOHUB (BẢN CHUẨN ĐẦY ĐỦ TỪ CODER)
# ==========================================
def _riohub_first(data, *keys):
    for key in keys:
        value = data.get(key)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            return value
    return None

def _riohub_identifier(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value).strip() or None

def _rio_db_error(error, data):
    private = []
    def collect(value):
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif value is not None:
            private.append(str(value))
    collect(data)
    private.extend(value for key, value in os.environ.items() if any(word in key.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')))
    message = str(error)
    for value in sorted(set(private), key=len, reverse=True):
        if value:
            message = message.replace(value, '[REDACTED]')
    message = re.sub(r'(?:sb_secret_|sb_publishable_)[A-Za-z0-9_.-]+', '[REDACTED]', message)
    message = re.sub(r'ey[J-Z][A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+', '[REDACTED]', message)
    return json.dumps(message, ensure_ascii=True)

def _riohub_unwrap(envelope):
    inner = envelope.get('data')
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except ValueError:
            inner = None
    if not isinstance(inner, dict):
        return envelope
    for key in ('order', 'conversion', 'transaction'):
        if isinstance(inner.get(key), dict):
            inner = dict(inner[key])
    print('RIOHUB data keys=' + json.dumps(sorted(inner.keys()), ensure_ascii=True), flush=True)
    merged = {key: value for key, value in envelope.items() if key != 'data'}
    merged.update(inner)
    return merged

@app.route('/api/riohub-webhook', methods=['GET', 'POST'])
def riohub_webhook():
    print('RIOHUB hit method=' + request.method + ' content_type=' + json.dumps(request.content_type, ensure_ascii=True) + ' query_keys=' + json.dumps(sorted(request.args.keys()), ensure_ascii=True), flush=True)
    body = request.get_json(silent=True)
    if body is None and request.form:
        body = request.form.to_dict()
    if body is None and request.method == 'GET':
        body = request.args.to_dict()
    if body is None:
        body = {}
    if not isinstance(body, dict):
        print('RIOHUB payload keys[]: invalid payload object', flush=True)
        return jsonify(ok=False, reason='invalid_payload'), 200

    print('RIOHUB payload keys=' + json.dumps(sorted(body.keys()), ensure_ascii=True), flush=True)
    data = _riohub_unwrap(body)

    order_id = _riohub_identifier(_riohub_first(data, 'order_id', 'order_sn', 'id'))
    if order_id is None:
        print('RIOHUB warning: missing_order_id', flush=True)
        return jsonify(ok=False, reason='missing_order_id'), 200

    sub_id = _riohub_identifier(_riohub_first(data, 'subid', 'sub1', 'sub_id', 'tag', 'user_sub_id', 'customer_id'))
    if sub_id is None:
        print('RIOHUB warning: missing_sub_id', flush=True)
        return jsonify(ok=False, reason='missing_sub_id'), 200

    raw_comm = _riohub_first(data, 'commission', 'est_commission', 'actual_commission', 'earned_commission')
    try:
        if isinstance(raw_comm, bool):
            raise ValueError('boolean commission')
        commission_goc = float(raw_comm) if raw_comm is not None else 0.0
        if not math.isfinite(commission_goc):
            raise ValueError('nonfinite commission')
    except (TypeError, ValueError, OverflowError):
        commission_goc = 0.0
        print('RIOHUB warning: missing_or_invalid_commission', flush=True)

    status = _riohub_identifier(_riohub_first(data, 'status', 'order_status'))
    thuc_nhan = commission_goc * CASHBACK_RATE if commission_goc is not None else None
    if thuc_nhan is not None and not math.isfinite(thuc_nhan):
        print('RIOHUB error: invalid cashback calculation', flush=True)
        return jsonify(ok=False, reason='invalid_cashback'), 500

    try:
        if supabase is None:
            raise RuntimeError('Supabase client unavailable')
        row = {
            'order_id': order_id,
            'user_id': sub_id,
            'commission_goc': commission_goc,
            'thuc_nhan': thuc_nhan,
            'status': status,
            'updated_at': datetime.now().isoformat()
        }
        row = {key: value for key, value in row.items() if value is not None}
        supabase.table('transactions').upsert(row, on_conflict='order_id').execute()
    except Exception as db_err:
        print('RIOHUB database error:', _rio_db_error(db_err, data), flush=True)
        return jsonify(ok=False, reason='database_error'), 500

    print('RIOHUB success: order_id=' + json.dumps(order_id, ensure_ascii=True), flush=True)
    return jsonify(ok=True), 200

# ==========================================
# 6.1 API KÍCH HOẠT QUÉT ĐƠN SHOPEE THỦ CÔNG
# ==========================================
@app.route('/api/sync-shopee', methods=['GET', 'POST'])
def trigger_sync_shopee():
    try:
        sync_shopee_orders()
        return jsonify({"success": True, "message": "Đã quét và đồng bộ đơn hàng Shopee thành công!"}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ==========================================
# PHẦN A: ĐOẠN CODE KỸ THUẬT YÊU CẦU THÊM VÀO TRƯỚC if __name__ == '__main__':
# ==========================================
import hmac
from decimal import Decimal

@app.route('/api/account-summary', methods=['GET'])
def joli_account_summary():
    expected = os.environ.get('ACCOUNT_API_SECRET', '')
    supplied = request.headers.get('X-Account-Secret', '')
    if not expected or not hmac.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')):
        return jsonify(ok=False), 401

    raw_user_id = request.args.get('user_id')
    if raw_user_id is None or raw_user_id == '':
        return jsonify(ok=False), 400

    user_id = validate_and_clean_sub_id(raw_user_id)
    if supabase is None:
        return jsonify(ok=False), 503

    approved_statuses = ['2', 'completed', 'approved', 'settled', 'paid']
    excluded_statuses = ['cancelled', 'refunded', 'rejected', 'invalid']

    pending = Decimal('0')
    approved = Decimal('0')
    total_orders = 0
    orders = []

    page_size = 50
    offset = 0

    try:
        while True:
            query = (
                supabase.table('transactions')
                .select('order_id, status, commission_goc, thuc_nhan, updated_at')
                .eq('user_id', user_id)
                .order('updated_at', desc=True)
                .limit(page_size)
            )
            if offset:
                query = query.range(offset, offset + page_size - 1)
            
            result = query.execute()
            rows = result.data
            if not isinstance(rows, list):
                raise ValueError('Invalid transaction response')

            for row in rows:
                cashback = Decimal(str(row.get('thuc_nhan') or 0))
                commission = Decimal(str(row.get('commission_goc') or 0))
                if not cashback.is_finite() or not commission.is_finite():
                    raise ValueError('Invalid transaction amount')

                status = str(row.get('status') or '').strip().lower()
                if status in approved_statuses:
                    approved += cashback
                elif status not in excluded_statuses:
                    pending += cashback

                if len(orders) < 50:
                    orders.append({
                        'order_id': row.get('order_id'),
                        'status': row.get('status'),
                        'commission_goc': float(commission),
                        'thuc_nhan': float(cashback),
                        'updated_at': row.get('updated_at')
                    })

            total_orders += len(rows)
            if len(rows) < page_size:
                break
            offset += page_size

        return jsonify(
            ok=True,
            user_id=user_id,
            balance_pending=float(pending),
            balance_approved=float(approved),
            total_orders=total_orders,
            orders=orders
        )
    except Exception:
        return jsonify(ok=False), 503

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Joli Affiliate Server is Running!", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    
