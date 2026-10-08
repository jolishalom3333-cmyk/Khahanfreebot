import os
import threading
import discord
from discord.ext import commands
from flask import Flask

# 1. Khởi động Flask web nhỏ để Render nhận diện cổng (Port)
app = Flask(__name__)


@app.route("/")
def home():
  return "Bot is running!"


def run_web():
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


# Chạy Flask ở một luồng riêng (background thread)
threading.Thread(target=run_web).start()

# 2. Cấu hình Discord Bot như bình thường
intents = discord.Intents.default()
intents.message_content = True
intents.guild_members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
  print(f"Bot đã sẵn sàng kết nối: {bot.user}")


@bot.event
async def on_message(message):
  if message.author == bot.user:
    return

  text = message.content

  # Bắt link mua hàng và chuyển đổi affiliate
  if "shopee.vn" in text or "tiktok.com" in text:
    affiliate_link = f"https://s.shopee.vn/link_mau_cua_ban?url={text}"
    await message.channel.send(
        f"✨ Link ưu đãi hoàn tiền của bạn:\n{affiliate_link}"
    )

  elif text.startswith("!sodu"):
    await message.channel.send("💰 Số dư hiện tại của bạn là: 0 VNĐ")

  await bot.process_commands(message)


# Khởi chạy Bot Discord
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
  bot.run(TOKEN)
    
