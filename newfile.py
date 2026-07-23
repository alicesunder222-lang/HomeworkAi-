import discord
from discord.ext import commands, tasks
from groq import Groq
import sqlite3
import datetime
import zoneinfo
import asyncio
import os
import sys
import base64

# ระบบสร้างเว็บจิ๋ว และระบบสะกิดตัวเองทุกๆ 1 นาที จบงานใน Render ตัวเดียว
from flask import Flask
from threading import Thread
import requests

app = Flask('')

@app.route('/')
def home():
    return "บอทการบ้าน เวอร์ชัน Slash Commands (รองรับวิชา/รายละเอียด/ไม่บังคับวันส่ง) พร้อมรัน 24 ชั่วโมง!"

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
# อัปเกรดตารางฐานข้อมูลรองรับ "subject" (วิชา) และปรับให้ "due_date" เป็นค่าว่างได้
cursor.execute('''
    CREATE TABLE IF NOT EXISTS homework (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        title TEXT NOT NULL,
        due_date TEXT,
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
    print(f'บอท {bot.user.name} ออนไลน์ระบบ Slash Commands เรียบร้อยแล้วครับน้า!')
    try:
        # ซิงค์ Slash Commands เข้ากับ Discord
        synced = await bot.tree.sync()
        print(f'Sync Slash Commands สำเร็จจำนวน {len(synced)} คำสั่ง')
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการ Sync Commands: {e}")

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
                    db_cursor.execute("SELECT id, subject, title, due_date FROM homework ORDER BY due_date ASC")
                    rows = db_cursor.fetchall()
                    
                    if rows:
                        channel = bot.get_channel(channel_id)
                        if channel:
                            embed = discord.Embed(
                                title="📝 รายการการบ้านและงานค้างทั้งหมด",
                                color=discord.Color.blue(),
                                timestamp=datetime.datetime.now(tz_thailand)
                            )
                            for row in rows:
                                due_text = row[3] if row[3] else "ไม่ระบุกำหนดส่ง"
                                embed.add_field(
                                    name=f"🔹 [ID: {row[0]}] วิชา: {row[1]}",
                                    value=f"📌 รายละเอียด: {row[2]}\n📅 กำหนดส่ง: **{due_text}**",
                                    inline=False
                                )
                            await channel.send(content="@everyone", embed=embed)
                
                db_cursor.execute("INSERT INTO alert_history (alert_date) VALUES (?)", (today_date,))
                db_conn.commit()
                    
            db_conn.close()
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในระบบแจ้งเตือนอัตโนมัติ: {e}")

# ==================== SLASH COMMANDS ====================

@bot.tree.command(name="แจ้งงาน", description="เปิดหรือปิดระบบแจ้งเตือนการบ้านตอน 7 โมงเช้า")
async def slash_set_notification(interaction: discord.Interaction, action: str):
    if action not in ["เปิด", "ปิด"]:
        await interaction.response.send_message("❌ กรุณาเลือกสถานะ 'เปิด' หรือ 'ปิด' เท่านั้นครับ", ephemeral=True)
        return

    channel_id = interaction.channel.id
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    
    is_val = 1 if action == "เปิด" else 0
    db_cursor.execute("REPLACE INTO notification_settings (channel_id, is_enabled) VALUES (?, ?)", (channel_id, is_val))
    db_conn.commit()
    db_conn.close()
    
    if action == "เปิด":
        embed = discord.Embed(title="✅ เปิดระบบแจ้งเตือนอัตโนมัติสำเร็จ", description="บอทจะรายงานการบ้านเวลา 07:00 น. ในห้องนี้ครับ", color=discord.Color.brand_green())
    else:
        embed = discord.Embed(title="🔕 ปิดระบบแจ้งเตือนอัตโนมัติ", description="ปิดการแจ้งเตือนตอน 7 โมงเช้าเรียบร้อยครับ", color=discord.Color.light_grey())
        
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="จด", description="บันทึกการบ้านหรือชิ้นงานใหม่ (วันส่งไม่บังคับ)")
async def slash_add_homework(interaction: discord.Interaction, subject: str, detail: str, due_date: str = None):
    formatted_date = None
    if due_date:
        try:
            # ตรวจสอบรูปแบบวันที่ ถ้าผู้ใช้กรอกมา
            datetime.datetime.strptime(due_date.strip(), '%Y-%m-%d')
            formatted_date = due_date.strip()
        except ValueError:
            await interaction.response.send_message("❌ รูปแบบวันที่ไม่ถูกต้อง! กรุณากรอกเป็น **ปี-เดือน-วัน** เช่น `2026-07-25` หรือเว้นว่างไว้หากไม่มีกำหนดส่ง", ephemeral=True)
            return

    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute(
        "INSERT INTO homework (subject, title, due_date, channel_id) VALUES (?, ?, ?, ?)",
        (subject, detail, formatted_date, interaction.channel.id)
    )
    db_conn.commit()
    db_conn.close()
    
    embed = discord.Embed(
        title="✅ บันทึกข้อมูลสำเร็จ",
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(tz_thailand)
    )
    embed.add_field(name="📚 วิชา", value=subject, inline=True)
    embed.add_field(name="📌 รายละเอียด", value=detail, inline=False)
    embed.add_field(name="📅 กำหนดส่ง", value=formatted_date if formatted_date else "ไม่ระบุ (ไม่มีกำหนด)", inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="การบ้าน", description="แสดงรายการการบ้านและงานทั้งหมดในระบบ")
async def slash_list_homework(interaction: discord.Interaction):
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute("SELECT id, subject, title, due_date FROM homework ORDER BY due_date ASC")
    rows = db_cursor.fetchall()
    db_conn.close()
    
    if not rows:
        embed = discord.Embed(
            title="🎉 ยินดีด้วย!",
            description="**ตอนนี้ไม่มีงานค้างในระบบเลยครับ!** สบายใจได้",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed)
        return
        
    embed = discord.Embed(
        title="📝 รายการการบ้านและงานทั้งหมด",
        color=discord.Color.blue(),
        timestamp=datetime.datetime.now(tz_thailand)
    )
    for row in rows:
        due_text = row[3] if row[3] else "ไม่ระบุกำหนดส่ง"
        embed.add_field(
            name=f"🔹 [ID: {row[0]}] วิชา: {row[1]}",
            value=f"📌 รายละเอียด: {row[2]}\n📅 กำหนดส่ง: **{due_text}**",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ลบ", description="ลบงานออกจากระบบด้วยรหัส ID")
async def slash_delete_homework(interaction: discord.Interaction, homework_id: int):
    db_conn = sqlite3.connect('homework.db')
    db_cursor = db_conn.cursor()
    db_cursor.execute("SELECT subject, title FROM homework WHERE id = ?", (homework_id,))
    row = db_cursor.fetchone()
    if row:
        db_cursor.execute("DELETE FROM homework WHERE id = ?", (homework_id,))
        db_conn.commit()
        
        embed = discord.Embed(
            title="🗑️ ลบงานสำเร็จ",
            description=f"นำงานวิชา **{row[0]}** ({row[1]}) ออกจากระบบเรียบร้อยแล้วครับ!",
            color=discord.Color.light_grey()
        )
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ ลบไม่สำเร็จ",
            description=f"ไม่พบงานรหัส ID: {homework_id} ในระบบ",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    db_conn.close()

# ==================== AI CONVERSATION & VISION SYSTEM ====================

def ask_groq_text(conversation_history):
    if not groq_client: return "❌ บอทยังไม่ได้ตั้งค่าคีย์ AI"
    messages = [{"role": "system", "content": "คุณคือผู้ช่วยตอบคำถามการบ้านภาษาไทยที่สุภาพ กระชับ และเข้าใจบริบทการสนทนาต่อเนื่อง"}]
    messages.extend(conversation_history)
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages
    )
    return response.choices[0].message.content

def ask_groq_vision(image_base64, user_prompt):
    if not groq_client: return "❌ บอทยังไม่ได้ตั้งค่าคีย์ AI"
    
    prompt_text = user_prompt if user_prompt else "ช่วยอ่านโจทย์การบ้านจากภาพนี้ แล้วอธิบายวิธีทำและคำตอบอย่างเป็นขั้นตอนให้หน่อยครับ"
    
    messages = [
        {"role": "system", "content": "คุณคือ AI ผู้เชี่ยวชาญการตรวจโจทย์และวิเคราะห์การบ้านจากรูปภาพ จงอ่านโจทย์ อธิบายวิธีทำ และสรุปคำตอบให้ชัดเจน สุภาพ สั้นกระชับ ภาษาไทย"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]
        }
    ]
    response = groq_client.chat.completions.create(
        model="llama-3.2-11b-vision-preview",
        messages=messages
    )
    return response.choices[0].message.content

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
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
        
        has_image = False
        image_url = None
        
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith('image/'):
                    has_image = True
                    image_url = attachment.url
                    break
        
        async with message.channel.typing():
            try:
                if has_image:
                    response_bytes = await asyncio.to_thread(requests.get, image_url)
                    image_base64 = base64.b64encode(response_bytes.content).decode('utf-8')
                    
                    reply_text = await asyncio.to_thread(ask_groq_vision, image_base64, user_question)
                    
                    embed = discord.Embed(
                        title="👁️🤖 ผลการวิเคราะห์โจทย์จากรูปภาพ",
                        description=reply_text,
                        color=discord.Color.teal()
                    )
                    await message.reply(embed=embed)
                    
                elif user_question:
                    conversation_history = []
                    
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
                    
                    reply_text = await asyncio.to_thread(ask_groq_text, conversation_history)
                    
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

