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
    return "บอทการบ้าน เวอร์ชันเสถียร (ความจำ AI ต่อเนื่อง) พร้อมรัน 24 ชั่วโมง!"

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
    print(f'บอท {bot.user.name} ออนไลน์ระบบเสถียร (ความจำต่อเนื่อง) เรียบร้อยแล้วครับน้า!')
    if not check_homework_reminders.is_running():
        check_homework_reminders.start()
    if not keep_alive_ping.is_running():
        keep_alive_ping.start()

# 1. 👑 ระบบรายงานการบ้านค้างตอนเช้า
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
                db_cursor.execute("SELECT channel_id FROM notification_settings WHERE is_enabled = 1")
                active_channels = db_cursor.fetchall()
                
                for (channel_id,) in active_channels:
                    db_cursor.execute("SELECT id, title, due_date FROM homework ORDER BY due_date ASC")
                    rows = db_cursor.fetchall()
                    
                    if rows:
                        channel = bot.get_channel(channel_id)
                        if channel:
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
                            await channel.send(content="@everyone", embed=embed)
                
                db_cursor.execute("INSERT INTO alert_history (alert_date) VALUES (?)", (today_date,))
                db_conn.commit()
                    
            db_conn.close()
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในระบบแจ้งเตือนอัตโนมัติ: {e}")

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
            description="บอทจะคอยรายงานการบ้านค้างทั้งหมดให้ตอน **07:00 น.** ในห้องนี้ทุกวันครับ",
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
            description="กรุณาพิมพ์ระบุสถานะด้วยครับ เช่น:\n`!แจ้งงาน เปิด`\n`!แจ้งงาน ปิด`",
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
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute("SELECT id, title, due_date FROM homework ORDER BY due_date ASC")
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

# ==================== AI CONVERSATION SYSTEM ====================
def ask_groq(conversation_history):
    if not groq_client: return "❌ บอทยังไม่ได้ตั้งค่าคีย์ AI"
    messages = [{"role": "system", "content": "คุณคือผู้ช่วยตอบคำถามการบ้านภาษาไทยที่สุภาพ กระชับ และเข้าใจบริบทการสนทนาต่อเนื่อง"}]
    messages.extend(conversation_history)
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages
    )
    return response.choices[0].message.content

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    # ตรวจสอบว่าเป็นการ Reply ข้อความของบอทหรือไม่
    is_reply_to_bot = False
    if message.reference and message.reference.message_id:
        try:
            replied_msg = await message.channel.fetch_message(message.reference.message_id)
            if replied_msg.author == bot.user:
                is_reply_to_bot = True
        except:
            pass

    if bot.user.mentioned_in(message) or is_reply_to_bot:
        user_question = message.content.replace(f'<@{bot.user.id}>', '').strip()
        
        if user_question:
            async with message.channel.typing():
                try:
                    conversation_history = []
                    
                    # ถ้าเป็นการ Reply บอทจะดึงข้อความย้อนหลังขึ้นไปสูงสุด 4 ข้อความมาสร้างบริบท
                    if message.reference and message.reference.message_id:
                        current_ref = message.reference
                        for _ in range(4): 
                            if not current_ref or not current_ref.message_id:
                                break
                            try:
                                old_msg = await message.channel.fetch_message(current_ref.message_id)
                                clean_content = old_msg.content.replace(f'<@{bot.user.id}>', '').strip()
                                
                                if old_msg.author == bot.user:
                                    if old_msg.embeds:
                                        clean_content = old_msg.embeds[0].description
                                    conversation_history.insert(0, {"role": "assistant", "content": clean_content})
                                else:
                                    conversation_history.insert(0, {"role": "user", "content": clean_content})
                                
                                current_ref = old_msg.reference
                            except:
                                break
                    
                    conversation_history.append({"role": "user", "content": user_question})
                    
                    reply_text = await asyncio.to_thread(ask_groq, conversation_history)
                    
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

