import os
import re
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands

# 1. Khởi động Web Server giả lập để duy trì Render (tránh bị sleep)
app = Flask("")


@app.route("/")
def home():
  Template = "Bot Discord Hoàn Tiền Shopee & TikTok đang hoạt động trực tuyến!"
  return Template


def run_web():
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


# 2. Cấu hình Discord Bot
intents = discord.Intents.default()
intents.message_content = True  # Bắt buộc bật để đọc nội dung tin nhắn
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
  print(f"Bot đã đăng nhập thành công dưới tên: {bot.user}")


@bot.event
async def on_message(message):
  # Không để bot tự phản hồi tin nhắn của chính nó
  if message.author == bot.user:
    return

  content = message.content

  # Kiểm tra xem tin nhắn có chứa link Shopee hoặc TikTok không
  has_shopee = "shopee.vn" in content or "shp.ee" in content
  has_tiktok = "tiktok.com" in content or "vt.tiktok.com" in content

  if has_shopee or has_tiktok:
    # Logic chuyển đổi link (Thay thế bằng link affiliate thực tế của bạn)
    # Ví dụ tạm thời: Gắn thêm mã tracking hoặc gọi API rút gọn
    affiliate_link = (
        f"{content}\n👉 *(Link đã được tự động chuyển đổi sang Affiliate)*"
    )

    # Gửi phản hồi lại kênh chat
    await message.reply(
        f"Cảm ơn {message.author.mention}! Đây là link mua hàng của bạn:\n{
            affiliate_link
        }"
    )

  # Xử lý các lệnh dạng prefix (ví dụ !sodu)
  await bot.process_commands(message)


# Lệnh kiểm tra số dư mẫu: gõ !sodu trong chat
@bot.command(name="sodu")
async def check_balance(ctx):
  # Bạn có thể kết nối database hoặc API lấy số dư thực tế của khách hàng ở đây
  balance = "0 VNĐ"
  await ctx.send(
      f"Hi {ctx.author.mention}, số dư tài khoản hoàn tiền của bạn hiện tại là:"
      f" **{balance}**"
  )


# 3. Chạy song song Web Server và Discord Bot
if __name__ == "__main__":
  # Chạy web server ở luồng riêng
  t = Thread(target=run_web)
  t.start()

  # Chạy Discord bot (Lấy Token từ biến môi trường trên Render)
  TOKEN = os.environ.get("DISCORD_TOKEN")
  if TOKEN:
    bot.run(TOKEN)
  else:
    print(
        "Lỗi: Chưa cấu hình biến môi trường DISCORD_TOKEN trên Render!"
    )
    
