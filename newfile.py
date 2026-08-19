import sys, types
if 'audioop' not in sys.modules:
    sys.modules['audioop'] = types.ModuleType('audioop')

import discord
from discord.ext import commands, tasks
from groq import Groq
import sqlite3
from datetime import datetime
import asyncio
import os
from threading import Thread
from flask import Flask

# ==================== KEEP ALIVE WEB SERVER ====================
# สร้าง Web Server สั้นๆ เพื่อตอบ Render ว่าแอปทำงานอยู่
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# ==================== CONFIGURATION ====================
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')

ANNOUNCE_CHANNEL_ID = int(os.environ.get('ANNOUNCE_CHANNEL_ID', 0))
HOMEWORK_CHANNEL_ID = int(os.environ.get('HOMEWORK_CHANNEL_ID', 0))

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ==================== DATABASE SETUP ====================
def init_db():
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
    conn.commit()
    conn.close()

init_db()

# ==================== BOT EVENTS & TASKS ====================
@bot.event
async def on_ready():
    print(f'บอท {bot.user.name} ออนไลน์แล้ว!')
    if ANNOUNCE_CHANNEL_ID != 0:
        announce_channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if announce_channel:
            await announce_channel.send("🟢 **[System Status]** บอทออนไลน์พร้อมใช้งานแล้วครับ!")

    if not check_homework_reminders.is_running():
        check_homework_reminders.start()

@tasks.loop(hours=1)
async def check_homework_reminders():
    try:
        now = datetime.now()
        if now.hour == 8:
            today = now.strftime('%Y-%m-%d')
            conn = sqlite3.connect('homework.db')
            cursor = conn.cursor()
            
            cursor.execute("SELECT id, title FROM homework WHERE due_date = ?", (today,))
            rows = cursor.fetchall()
            
            if rows:
                target_channel = bot.get_channel(HOMEWORK_CHANNEL_ID)
                for row in rows:
                    hw_id, title = row
                    if target_channel:
                        await target_channel.send(f"🚨 **[แจ้งเตือนการบ้าน]** @everyone \nงาน: **{title}** มีกำหนดส่งภายใน **วันนี้แล้วนะ!** 📝🔥")
                    cursor.execute("DELETE FROM homework WHERE id = ?", (hw_id,))
            
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในระบบแจ้งเตือน: {e}")

# ==================== COMMANDS ====================

@bot.command(name='จด')
async def add_homework(ctx, title: str, due_date: str):
    try:
        datetime.strptime(due_date, '%Y-%m-%d')
        conn = sqlite3.connect('homework.db')
        cursor = conn.cursor()
        channel_to_save = HOMEWORK_CHANNEL_ID if HOMEWORK_CHANNEL_ID != 0 else ctx.channel.id
        cursor.execute(
            "INSERT INTO homework (title, due_date, channel_id) VALUES (?, ?, ?)",
            (title, due_date, channel_to_save)
        )
        conn.commit()
        conn.close()
        await ctx.reply(f"✅ บันทึกสำเร็จ: **{title}** \n📅 กำหนดส่ง: {due_date}")
    except ValueError:
        await ctx.reply("❌ รูปแบบวันที่ไม่ถูกต้อง! กรุณาพิมพ์เป็น **ปี-เดือน-วัน** เช่น `!จด การบ้านคณิต 2026-07-15`")

@bot.command(name='การบ้าน')
async def list_homework(ctx):
    conn = sqlite3.connect('homework.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, due_date FROM homework ORDER BY due_date ASC")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return
        
    msg = "📝 **รายการการบ้านปัจจุบัน:**\n"
    for row in rows:
        msg += f"🔹 [ID: {row[0]}] **{row[1]}** - ส่งวันที่ {row[2]}\n"
    await ctx.reply(msg)

@bot.command(name='ลบ')
async def delete_homework(ctx, homework_id: int):
    conn = sqlite3.connect('homework.db')
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM homework WHERE id = ?", (homework_id,))
    row = cursor.fetchone()
    
    if row:
        cursor.execute("DELETE FROM homework WHERE id = ?", (homework_id,))
        conn.commit()
        await ctx.reply(f"🗑️ ลบการบ้านงาน **\"{row[0]}\"** เรียบร้อยแล้ว!")
    else:
        await ctx.reply(f"❌ ไม่พบการบ้านรหัส ID: {homework_id}")
        
    conn.close()

def ask_groq(user_question):
    if not groq_client:
        return "❌ บอทยังไม่ได้ตั้งค่าคีย์ AI"
    
    prompt = f"คุณคือบอทผู้ช่วยทำการบ้านใน Discord จงตอบคำถามนี้อย่างกระชับ เข้าใจง่าย: {user_question}"
    
    response = groq_client.chat.completions.create(
        model="llama-3.1-70b-versatile",
        messages=[
            {"role": "system", "content": "คุณคือผู้ช่วยตอบคำถามการบ้านภาษาไทย"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

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

# ==================== START BOT ====================
if __name__ == '__main__':
    keep_alive()  # รันเว็บเซิร์ฟเวอร์หลอกฝั่ง Background
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)

