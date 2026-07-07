import discord
from discord.ext import commands, tasks
from groq import Groq
import sqlite3
import datetime
import zoneinfo
import asyncio
import os
import sys

# ==================== CONFIGURATION ====================
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ตั้งค่าโซนเวลาไทย
tz_thailand = zoneinfo.ZoneInfo("Asia/Bangkok")

# ==================== DATABASE SETUP ====================
conn = sqlite3.connect('homework.db')
cursor = conn.cursor()
# สร้างตารางจดการบ้าน
cursor.execute('''
    CREATE TABLE IF NOT EXISTS homework (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        due_date TEXT NOT NULL,
        channel_id INTEGER NOT NULL
    )
''')
# 👑 เพิ่มตารางพิเศษ: เอาไว้จำว่า "วันนี้บอทกดแจ้งเตือนไปแล้วหรือยัง" ป้องกันการส่งซ้ำตอนบอทรีสตาร์ทบ่อยๆ
cursor.execute('''
    CREATE TABLE IF NOT EXISTS alert_history (
        alert_date TEXT PRIMARY KEY
    )
''')
conn.commit()

# ==================== BOT EVENTS & TASKS ====================
@bot.event
async def on_ready():
    print(f'บอท {bot.user.name} ออนไลน์ด้วยระบบกันตาย (เปิดปิดบ่อยก็ไม่พลาดเตือน) บน Render แล้วครับ!')
    if not check_homework_reminders.is_running():
        check_homework_reminders.start()
    if not auto_restart_bot.is_running():
        auto_restart_bot.start()

# 1. ระบบเช็กการบ้านอัตโนมัติ (วิ่งเช็กทุกๆ 10 นาที เพื่อความแข็งแรงและแม่นยำสูงสุด)
@tasks.loop(minutes=10)
async def check_homework_reminders():
    try:
        now_th = datetime.datetime.now(tz_thailand)
        current_time = now_th.time()
        today_date = now_th.strftime('%Y-%m-%d')
        
        # 💡 เงื่อนไขเหล็ก: ถ้าเวลาปัจจุบัน "เลยเวลา 07:00 น. เป็นต้นไป" ถึงจะเริ่มทำงาน
        if current_time >= datetime.time(7, 0, 0):
            
            db_conn = sqlite3.connect('homework.db')
            db_cursor = db_conn.cursor()
            
            # เช็กก่อนว่า "วันนี้" บอทเคยส่งแจ้งเตือนไปแล้วหรือยัง?
            db_cursor.execute("SELECT alert_date FROM alert_history WHERE alert_date = ?", (today_date,))
            already_sent = db_cursor.fetchone()
            
            # ถ้ายัดงานไม่เคยส่งเลยในวันนี้ ให้ลุยเตือนทันที!
            if not already_sent:
                # ค้นหาการบ้านที่มีกำหนดส่ง "วันนี้"
                db_cursor.execute("SELECT id, title, channel_id FROM homework WHERE due_date = ?", (today_date,))
                rows = db_cursor.fetchall()
                
                if rows:
                    for row in rows:
                        hw_id, title, channel_id = row
                        channel = bot.get_channel(channel_id)
                        if channel:
                            await channel.send(f"🚨 **[แจ้งเตือนการบ้านวันต่อวัน]** @everyone \nงาน: **{title}** มีกำหนดส่งภายใน **วันนี้แล้วนะ!** อย่าลืมเคลียร์กันด้วยครับ 📝🔥")
                            # แจ้งเตือนเสร็จ ลบงานนั้นออกจากระบบทันที
                            db_cursor.execute("DELETE FROM homework WHERE id = ?", (hw_id,))
                    
                    # 👑 บันทึกประวัติไว้ว่า "วันนี้เตือนรอบใหญ่เสร็จแล้วนะ" บอทรีสตาร์ทกี่รอบหลังจากนี้ก็จะไม่ส่งซ้ำซาก
                    db_cursor.execute("INSERT INTO alert_history (alert_date) VALUES (?)", (today_date,))
                    db_conn.commit()
                    
            db_conn.close()
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

# 📥 !จด [ชื่องาน] [ปี-เดือน-วัน]
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

# 📋 !การบ้าน (หากไม่มีงานค้างเพิ่ม จะเงียบกริบ)
@bot.command(name='การบ้าน')
async def list_homework(ctx):
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute("SELECT id, title, due_date FROM homework ORDER BY due_date ASC")
    rows = db_cursor.fetchall()
    db_conn.close()
    
    if not rows:
        return
        
    msg = "📝 **รายการการบ้านปัจจุบัน:**\n"
    for row in rows:
        msg += f"🔹 [ID: {row[0]}] **{row[1]}** - ส่งวันที่ {row[2]}\n"
    await ctx.reply(msg)

# 🗑️ !ลบ [เลข ID ของงาน]
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

# 🤖 ระบบสมองกล Groq AI (Llama 3)
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

# 💬 ดักจับการแท็กบอท
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

if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("❌ ไม่พบ DISCORD_TOKEN ในระบบ")

