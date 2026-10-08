import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot đã sẵn sàng: {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    text = message.content

    # Bắt link mua hàng và chuyển đổi affiliate
    if "shopee.vn" in text or "tiktok.com" in text:
        affiliate_link = f"https://s.shopee.vn/link_mau_cua_ban?url={text}"
        await message.channel.send(f"✨ Link ưu đãi hoàn tiền của bạn:\n{affiliate_link}")

    elif text.startswith("!sodu"):
        await message.channel.send("💰 Số dư hiện tại của bạn là: 0 VNĐ")

    await bot.process_commands(message)

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
    
