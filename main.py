import os
import re
import time
import hashlib
import requests
import telebot

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHOPEE_APP_ID = os.getenv("SHOPEE_APP_ID")
SHOPEE_SECRET = os.getenv("SHOPEE_SECRET")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def get_shopee_affiliate_link(original_url):
    timestamp = int(time.time())
    query = f'''
    mutation {{
        generateShortLink(input: {{ originUrl: "{original_url}" }}) {{
            shortLink
        }}
    }}
    '''
    payload = f'{{"query": "{query}"}}'
    
    base_str = f"{SHOPEE_APP_ID}{timestamp}{payload}{SHOPEE_SECRET}"
    signature = hashlib.sha256(base_str.encode('utf-8')).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'SHA256 Credential={SHOPEE_APP_ID}, Timestamp={timestamp}, Signature={signature}'
    }

    try:
        response = requests.post("https://open-api.affiliate.shopee.vn/graphql", headers=headers, data=payload.encode('utf-8'), timeout=10)
        res_data = response.json()
        return res_data.get('data', {}).get('generateShortLink', {}).get('shortLink')
    except Exception as e:
        print("Lỗi API Shopee:", e)
        return None

@bot.message_handler(func=lambda message: True)
def process_message(message):
    text = message.text
    urls = re.findall(r'https?://[^\s]+', text)
    
    if not urls:
        bot.reply_to(message, "👋 Chào bạn! Hãy gửi cho mình một đường link Shopee để lấy link hoàn tiền nhé.")
        return

    url = urls[0]
    
    if "shopee.vn" in url or "shope.ee" in url:
        bot.reply_to(message, "⏳ Đang tạo link Shopee hoàn tiền...")
        aff_link = get_shopee_affiliate_link(url)
        if aff_link:
            bot.send_message(message.chat.id, f"✅ **Link mua hàng Shopee hoàn tiền của bạn:**\n👉 {aff_link}", parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "❌ Lỗi tạo link Shopee. Vui lòng kiểm tra lại link hoặc cấu hình API.")
    else:
        bot.send_message(message.chat.id, "⚠️ Hiện tại bot hỗ trợ tốt nhất cho link Shopee. Vui lòng dán đúng link Shopee!")

if __name__ == "__main__":
    print("Bot Khahanfreebot đang chạy...")
    bot.infinity_polling()
  
