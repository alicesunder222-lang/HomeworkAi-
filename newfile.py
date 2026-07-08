import discord
from discord.ext import commands, tasks
from groq import Groq
import sqlite3
import datetime
import zoneinfo
import asyncio
import os
import sys

# 👑 ระบบสร้างเว็บจิ๋ว และระบบสะกิดตัวเองทุกๆ 1 นาที จบงานใน Render ตัวเดียว
from flask import Flask
from threading import Thread
import requests

app = Flask('')

@app.route('/')
def home():
    return "บอทการบ้านสแตนด์บาย 24 ชั่วโมง ด้วยระบบยิงสะกิดตัวเองทุก 1 นาที!"

def run_web_server():
    app.run(host='0.0.0.0', port=10000)

# 🔥 ปรับใหม่: วิ่งสะกิดตัวเองถี่ยิบ "ทุกๆ 1 นาที" ไม่ยอมให้เครื่องหลับเด็ดขาด
@tasks.loop(minutes=1)
async def keep_alive_ping():
    my_url = os.environ.get('MY_BOT_URL')
    if my_url:
        try:
            await asyncio.to_thread(requests.get, my_url)
            print("🔄 [Self-Ping] ยิงสะกิดตัวเองสำเร็จ (ทุก 1 นาที) เครื่องตื่นตัวสุดๆ!")
        except Exception as e:
            print(f"❌ [Self-Ping] เคาะเรียกตัวเองไม่สำเร็จ: {e}")

# ==================== CONFIGURATION ====================
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

tz_thailand = zoneinfo.ZoneInfo("Asia/Bangkok")

# ==================== DATABASE SETUP ====================
conn = sqlite3.connect('homework.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS homework (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        due_date TEXT NOT NULL,
        channel_id INTEGER NOT NULL
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS alert_history (
        alert_date TEXT PRIMARY KEY
    )
''')
conn.commit()

# ==================== BOT EVENTS & TASKS ====================
@bot.event
async def on_ready():
    print(f'บอท {bot.user.name} ออนไลน์แบบจบในตัวเดียว ยิงสะกิดทุก 1 นาที แล้วครับน้า!')
    if not check_homework_reminders.is_running():
        check_homework_reminders.start()
    if not auto_restart_bot.is_running():
        auto_restart_bot.start()
    if not keep_alive_ping.is_running():
        keep_alive_ping.start()

# 1. ระบบเช็กการบ้านอัตโนมัติ (วิ่งส่องทุกๆ 10 นาที เลย 7 โมงเมื่อไหร่เตือนทันที)
@tasks.loop(minutes=10)
async def check_homework_reminders():
    try:
        now_th = datetime.datetime.now(tz_thailand)
        current_time = now_th.time()
        today_date = now_th.strftime('%Y-%m-%d')
        
        if current_time >= datetime.time(7, 0, 0):
            db_conn = sqlite3.connect('homework.db')
            db_cursor = db_conn.cursor()
            
            db_cursor.execute("SELECT alert_date FROM alert_history WHERE alert_date = ?", (today_date,))
            already_sent = db_cursor.fetchone()
            
            if not already_sent:
                db_cursor.execute("SELECT id, title, channel_id FROM homework WHERE due_date = ?", (today_date,))
                rows = db_cursor.fetchall()
                
                if rows:
                    for row in rows:
                        hw_id, title, channel_id = row
                        channel = bot.get_channel(channel_id)
                        if channel:
                            await channel.send(f"🚨 **[แจ้งเตือนการบ้านวันต่อวัน]** @everyone \nงาน: **{title}** มีกำหนดส่งภายใน **วันนี้แล้วนะ!** 📝🔥")
                            db_cursor.execute("DELETE FROM homework WHERE id = ?", (hw_id,))
                    
                    db_cursor.execute("INSERT INTO alert_history (alert_date) VALUES (?)", (today_date,))
                    db_conn.commit()
                    
            db_conn.close()
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในระบบแจ้งเตือน: {e}")

# 2. ระบบรีสตาร์ทตัวเองอัตโนมัติทุกๆ 1 ชั่วโมง
@tasks.loop(hours=1)
async def auto_restart_bot():
    if auto_restart_bot.current_loop == 0:
        return
    print("🔄 ครบ 1 ชั่วโมง: กำลังรีสตาร์ทบอทอัตโนมัติ...")
    await bot.close()
    conn.close()
    os.execv(sys.executable, ['python'] + sys.argv)

# ==================== COMMANDS ====================
@bot.command(name='จด')
async def add_homework(ctx, title: str, due_date: str):
    try:
        datetime.datetime.strptime(due_date, '%Y-%m-%d')
        db_conn = sqlite3.connect('homework.db')
        db_cursor = db_conn.cursor()
        db_cursor.execute(
            "INSERT INTO homework (title, due_date, channel_id) VALUES (?, ?, ?)",
            (title, due_date, ctx.channel.id)
        )
        db_conn.commit()
        db_conn.close()
        await ctx.reply(f"✅ บันทึกสำเร็จ: **{title}** \n📅 กำหนดส่ง: {due_date}")
    except ValueError:
        await ctx.reply("❌ รูปแบบวันที่ไม่ถูกต้อง! กรุณาพิมพ์เป็น **ปี-เดือน-วัน** เช่น `!จด การบ้านคณิต 2026-07-15`")

@bot.command(name='การบ้าน')
async def list_homework(ctx):
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute("SELECT id, title, due_date FROM homework ORDER BY due_date ASC")
    rows = db_cursor.fetchall()
    db_conn.close()
    if not rows: return
    msg = "📝 **รายการการบ้านปัจจุบัน:**\n"
    for row in rows:
        msg += f"🔹 [ID: {row[0]}] **{row[1]}** - ส่งวันที่ {row[2]}\n"
    await ctx.reply(msg)

@bot.command(name='ลบ')
async def delete_homework(ctx, homework_id: int):
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute("SELECT title FROM homework WHERE id = ?", (homework_id,))
    row = db_cursor.fetchone()
    if row:
        db_cursor.execute("DELETE FROM homework WHERE id = ?", (homework_id,))
        db_conn.commit()
        await ctx.reply(f"🗑️ ลบการบ้านงาน **\"{row[0]}\"** ออกจากระบบเรียบร้อยแล้วครับ!")
    else:
        await ctx.reply(f"❌ ไม่พบการบ้านรหัส ID: {homework_id} ในระบบ")
    db_conn.close()

def ask_groq(user_question):
    if not groq_client: return "❌ บอทยังไม่ได้ตั้งค่าคีย์ AI"
    prompt = f"คุณคือบอทผู้ช่วยทำการบ้านใน Discord จงตอบคำถามนี้อย่างกระชับ: {user_question}"
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "คุณคือผู้ช่วยตอบคำถามการบ้านภาษาไทยที่สุภาพและกระชับ"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    if bot.user.mentioned_in(message):
        user_question = message.content.replace(f'<@{bot.user.id}>', '').strip()
        if user_question:
            async with message.channel.typing():
                try:
                    reply_text = await asyncio.to_thread(ask_groq, user_question)
                    await message.reply(reply_text)
                except Exception as e:
                    await message.reply(f"❌ ระบบ Groq AI ขัดข้อง: {e}")
    await bot.process_commands(message)

if __name__ == "__main__":
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()
    
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ ไม่พบ DISCORD_TOKEN ในระบบ")

