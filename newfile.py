import discord
from discord.ext import commands, tasks
from groq import Groq  # ระบบประมวลผล Groq AI
import sqlite3
from datetime import datetime, timedelta
import asyncio
import os
import sys

# ==================== CONFIGURATION ====================
# ตั้งค่าคีย์และโทเค็นผ่าน Environment Variables บน Render
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')

# เปิดใช้งาน Groq Client
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

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
conn.commit()

# ==================== BOT EVENTS & TASKS ====================
@bot.event
async def on_ready():
    print(f'บอท {bot.user.name} ออนไลน์พร้อมระบบแจ้งเตือนวันต่อวันบน Render แล้วครับ!')
    if not check_homework_reminders.is_running():
        check_homework_reminders.start()
    if not auto_restart_bot.is_running():
        auto_restart_bot.start()

# 1. ระบบเช็กการบ้านอัตโนมัติ (แจ้งเตือนแบบวันต่อวัน รันทุกๆ 24 ชั่วโมง)
@tasks.loop(hours=24)
async def check_homework_reminders():
    try:
        current_conn = sqlite3.connect('homework.db')
        current_cursor = current_conn.cursor()
        
        # ดึงวันที่ปัจจุบัน (วันนี้) มาเช็กงานแบบวันต่อวัน
        today = datetime.now().strftime('%Y-%m-%d')
        
        # ค้นหาการบ้านที่มีกำหนดส่ง "วันนี้"
        current_cursor.execute("SELECT id, title, channel_id FROM homework WHERE due_date = ?", (today,))
        rows = current_cursor.fetchall()
        
        # เงื่อนไข: ถ้ามีการบ้านที่ต้องส่งวันนี้ ถึงจะส่งข้อความ (หากไม่มีงานจะไม่แสดงอะไรเลย)
        if rows:
            for row in rows:
                hw_id, title, channel_id = row
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"🚨 **[แจ้งเตือนการบ้านวันต่อวัน]** @everyone \nงาน: **{title}** มีกำหนดส่งภายใน **วันนี้แล้วนะ!** อย่าลืมเคลียร์กันด้วยครับ 📝🔥")
                    # แจ้งเตือนเสร็จ ลบงานนั้นออกจากฐานข้อมูลทันทีเพื่อไม่ให้ค้างข้ามวัน
                    current_cursor.execute("DELETE FROM homework WHERE id = ?", (hw_id,))
                    current_conn.commit()
                    
        current_conn.close()
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในระบบแจ้งเตือน: {e}")

# 2. ระบบรีสตาร์ทตัวเองอัตโนมัติทุกๆ 1 ชั่วโมงเพื่อเคลียร์ความจำ 🔄
@tasks.loop(hours=1)
async def auto_restart_bot():
    if auto_restart_bot.current_loop == 0:
        return
        
    print("🔄 ครบ 1 ชั่วโมง: กำลังรีสตาร์ทบอทอัตโนมัติ...")
    await bot.close()
    conn.close()
    os.execv(sys.executable, ['python'] + sys.argv)

# ==================== COMMANDS ====================

# 📥 คำสั่งสั่งจดการบ้าน: !จด [ชื่องาน] [ปี-เดือน-วัน]
@bot.command(name='จด')
async def add_homework(ctx, title: str, due_date: str):
    try:
        # ตรวจสอบรูปแบบวันที่ให้ถูกต้อง
        datetime.strptime(due_date, '%Y-%m-%d')
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

# 📋 คำสั่งดูรายการการบ้านทั้งหมด: !การบ้าน (หากไม่มีงานค้างเพิ่มเติม จะไม่แสดงข้อความใดๆ เลย)
@bot.command(name='การบ้าน')
async def list_homework(ctx):
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute("SELECT id, title, due_date FROM homework ORDER BY due_date ASC")
    rows = db_cursor.fetchall()
    db_conn.close()
    
    # หากไม่มีงานค้างเพิ่ม จะไม่แสดงข้อความใดๆ เลยตามเงื่อนไข
    if not rows:
        return
        
    msg = "📝 **รายการการบ้านปัจจุบัน:**\n"
    for row in rows:
        # แสดง ID ด้านหน้าเพื่อง่ายต่อการสั่งลบด้วยมือ
        msg += f"🔹 [ID: {row[0]}] **{row[1]}** - ส่งวันที่ {row[2]}\n"
    await ctx.reply(msg)

# 🗑️ คำสั่งลบงานแบบระบุเอง: !ลบ [เลข ID ของงาน]
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

# 🤖 ฟังก์ชันเชื่อมต่อกับ Groq AI (โมเดล Llama 3)
def ask_groq(user_question):
    if not groq_client:
        return "❌ บอทยังไม่ได้ตั้งค่าคีย์ AI (กรุณาใส่ GROQ_API_KEY)"
    
    prompt = f"คุณคือบอทผู้ช่วยทำการบ้านใน Discord จงตอบคำถามนี้อย่างกระชับ เข้าใจง่าย และถูกต้องตามหลักวิชาการ: {user_question}"
    
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "คุณคือผู้ช่วยตอบคำถามการบ้านภาษาไทยที่สุภาพและกระชับ"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

# 💬 ระบบดักจับข้อความและการแท็กเพื่อคุยกับ AI
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # ตรวจสอบว่าบอทโดนแท็กเพื่อถามคำถามหรือไม่
    if bot.user.mentioned_in(message):
        user_question = message.content.replace(f'<@{bot.user.id}>', '').strip()
        if user_question:
            async with message.channel.typing():
                try:
                    # แยกเธรดการทำงานของ AI ไม่ให้ดึงบอทดิสคอร์ดหลักหลุดออนไลน์
                    reply_text = await asyncio.to_thread(ask_groq, user_question)
                    await message.reply(reply_text)
                except Exception as e:
                    await message.reply(f"❌ ระบบ Groq AI ขัดข้อง: {e}")

    await bot.process_commands(message)

# รันระบบบอท
if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("❌ ไม่พบ DISCORD_TOKEN ในระบบ")
