import discord
from discord.ext import commands, tasks
from groq import Groq
import sqlite3
import datetime
import zoneinfo
import asyncio
import os
import sys

# ระบบสร้างเว็บจิ๋ว และระบบสะกิดตัวเองทุกๆ 1 นาที จบงานใน Render ตัวเดียว
from flask import Flask
from threading import Thread
import requests

app = Flask('')

@app.route('/')
def home():
    return "บอทการบ้าน เวอร์ชัน Embed ฝาแฝด !การบ้าน พร้อมรัน 24 ชั่วโมง!"

def run_web_server():
    app.run(host='0.0.0.0', port=10000)

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
    CREATE TABLE IF NOT EXISTS notification_settings (
        channel_id INTEGER PRIMARY KEY,
        is_enabled INTEGER DEFAULT 0
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
    print(f'บอท {bot.user.name} ออนไลน์ระบบ Embed ฝาแฝดเรียบร้อยแล้วครับน้า!')
    if not check_homework_reminders.is_running():
        check_homework_reminders.start()
    if not auto_restart_bot.is_running():
        auto_restart_bot.start()
    if not keep_alive_ping.is_running():
        keep_alive_ping.start()

# 1. 👑 ระบบเช็กการบ้านอัตโนมัติ (ปรับหน้าตา Embed ให้เป็นแบบเดียวกับ !การบ้าน เป๊ะๆ)
@tasks.loop(minutes=10)
async def check_homework_reminders():
    try:
        now_th = datetime.datetime.now(tz_thailand)
        current_time = now_th.time()
        today_date = now_th.strftime('%Y-%m-%d')
        
        if current_time >= datetime.time(7, 50, 0):
            db_conn = sqlite3.connect('homework.db')
            db_cursor = db_conn.cursor()
            
            db_cursor.execute("SELECT alert_date FROM alert_history WHERE alert_date = ?", (today_date,))
            already_sent = db_cursor.fetchone()
            
            if not already_sent:
                # ลบงานเก่าที่เลยกำหนดส่งทิ้งทันที
                db_cursor.execute("DELETE FROM homework WHERE due_date < ?", (today_date,))
                db_conn.commit()
                
                db_cursor.execute("SELECT channel_id FROM notification_settings WHERE is_enabled = 1")
                active_channels = db_cursor.fetchall()
                
                for (channel_id,) in active_channels:
                    db_cursor.execute("SELECT id, title, due_date FROM homework WHERE due_date >= ? ORDER BY due_date ASC", (today_date,))
                    rows = db_cursor.fetchall()
                    
                    if rows:
                        channel = bot.get_channel(channel_id)
                        if channel:
                            # 👑 ใช้ Embed สีฟ้า และหัวข้อเดียวกับคำสั่ง !การบ้าน เป๊ะๆ ตามที่น้าต้องการ
                            embed = discord.Embed(
                                title="📝 รายการการบ้านที่ต้องส่งทั้งหมดตอนนี้",
                                color=discord.Color.blue(),
                                timestamp=datetime.datetime.now(tz_thailand)
                            )
                            for row in rows:
                                embed.add_field(
                                    name=f"🔹 [ID: {row[0]}] {row[1]}",
                                    value=f"📅 กำหนดส่ง: **{row[2]}**",
                                    inline=False
                                )
                            
                            # ส่งแจ้งเตือนแบบแท็ก @everyone คู่กับกล่องคู่แฝด !การบ้าน
                            await channel.send(content="@everyone", embed=embed)
                
                db_cursor.execute("INSERT INTO alert_history (alert_date) VALUES (?)", (today_date,))
                db_conn.commit()
                    
            db_conn.close()
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในระบบแจ้งเตือนอัตโนมัติ: {e}")

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

@bot.command(name='แจ้งงาน')
async def set_notification(ctx, action: str = None):
    channel_id = ctx.channel.id
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    
    if action == "เปิด":
        db_cursor.execute("REPLACE INTO notification_settings (channel_id, is_enabled) VALUES (?, 1)", (channel_id,))
        db_conn.commit()
        
        embed = discord.Embed(
            title="✅ เปิดระบบแจ้งเตือนอัตโนมัติสำเร็จ",
            description="บอทจะคอยรายงานการบ้านค้างทั้งหมดให้ตอน **07:00 น.** ในห้องนี้ทุกวันครับ! (หากไม่มีการบ้านเหลืออยู่เลย ระบบจะเงียบกริบให้ครับ)",
            color=discord.Color.brand_green()
        )
        await ctx.send(embed=embed)
        
    elif action == "ปิด":
        db_cursor.execute("REPLACE INTO notification_settings (channel_id, is_enabled) VALUES (?, 0)", (channel_id,))
        db_conn.commit()
        
        embed = discord.Embed(
            title="🔕 ปิดระบบแจ้งเตือนอัตโนมัติ",
            description="ปิดการแจ้งเตือนตอน 7 โมงเช้าในห้องนี้เรียบร้อยครับ",
            color=discord.Color.light_grey()
        )
        await ctx.send(embed=embed)
        
    else:
        embed = discord.Embed(
            title="❌ วิธีใช้คำสั่งแจ้งงาน",
            description="กรุณาพิมพ์ระบุสถานะด้วยครับน้า เช่น:\n`!แจ้งงาน เปิด` - เพื่อเปิดระบเตือน 7 โมงเช้า\n`!แจ้งงาน ปิด` - เพื่อปิดระบบเตือน",
            color=discord.Color.orange()
        )
        await ctx.reply(embed=embed)
    
    db_conn.close()

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
        
        embed = discord.Embed(
            title="✅ บันทึกการบ้านสำเร็จ",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(tz_thailand)
        )
        embed.add_field(name="📝 ชื่องาน / วิชา", value=title, inline=True)
        embed.add_field(name="📅 กำหนดส่ง", value=due_date, inline=True)
        await ctx.reply(embed=embed)
    except ValueError:
        embed = discord.Embed(
            title="❌ บันทึกไม่สำเร็จ",
            description="รูปแบบวันที่ไม่ถูกต้อง! กรุณาพิมพ์เป็น **ปี-เดือน-วัน** เช่น `!จด การบ้านคณิต 2026-07-15`",
            color=discord.Color.dark_red()
        )
        await ctx.reply(embed=embed)

@bot.command(name='การบ้าน')
async def list_homework(ctx):
    now_th = datetime.datetime.now(tz_thailand)
    today_date = now_th.strftime('%Y-%m-%d')
    
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute("SELECT id, title, due_date FROM homework WHERE due_date >= ? ORDER BY due_date ASC", (today_date,))
    rows = db_cursor.fetchall()
    db_conn.close()
    
    if not rows:
        embed = discord.Embed(
            title="🎉 ยินดีด้วย!",
            description="**ตอนนี้ไม่มีการบ้านค้างในระบบเลยครับ!** สบายใจได้",
            color=discord.Color.gold()
        )
        await ctx.reply(embed=embed)
        return
        
    embed = discord.Embed(
        title="📝 รายการการบ้านที่ต้องส่งทั้งหมดตอนนี้",
        color=discord.Color.blue(),
        timestamp=datetime.datetime.now(tz_thailand)
    )
    for row in rows:
        embed.add_field(
            name=f"🔹 [ID: {row[0]}] {row[1]}",
            value=f"📅 กำหนดส่ง: **{row[2]}**",
            inline=False
        )
    await ctx.reply(embed=embed)

@bot.command(name='ลบ')
async def delete_homework(ctx, homework_id: int):
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute("SELECT title FROM homework WHERE id = ?", (homework_id,))
    row = db_cursor.fetchone()
    if row:
        db_cursor.execute("DELETE FROM homework WHERE id = ?", (homework_id,))
        db_conn.commit()
        
        embed = discord.Embed(
            title="🗑️ ลบการบ้านสำเร็จ",
            description=f"นำงาน **\"{row[0]}\"** ออกจากระบบเรียบร้อยแล้วครับ!",
            color=discord.Color.light_grey()
        )
        await ctx.reply(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ ลบไม่สำเร็จ",
            description=f"ไม่พบการบ้านรหัส ID: {homework_id} ในระบบ",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)
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
                    embed = discord.Embed(
                        title="🤖 คำตอบจาก AI ผู้ช่วยทำการบ้าน",
                        description=reply_text,
                        color=discord.Color.purple()
                    )
                    await message.reply(embed=embed)
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

