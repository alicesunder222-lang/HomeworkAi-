import sys, types
if 'audioop' not in sys.modules:
    sys.modules['audioop'] = types.ModuleType('audioop')

import os
import sqlite3
from datetime import datetime
import asyncio
from threading import Thread

import discord
from discord.ext import commands
from discord import app_commands, ui
from flask import Flask
from groq import Groq

# ==================== WEB SERVER FOR RENDER ====================
app = Flask('')

@app.route('/')
def home():
    return "Bot System is Active!"

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

# ID ของช่องที่ 3 (ช่องคลังบันทึกการบ้าน)
STORAGE_CHANNEL_ID = int(os.environ.get('STORAGE_CHANNEL_ID', 0))

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

intents = discord.Intents.default()
intents.message_content = True

class HomeworkBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Sync Slash Commands เรียบร้อยแล้ว!")

bot = HomeworkBot()

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect('homework.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            due_date TEXT NOT NULL,
            storage_msg_id INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==================== UI COMPONENTS & MODALS ====================

# แบบฟอร์มกรอกข้อมูลการบ้าน (สำหรับช่อง 2 Admin)
class AddHomeworkModal(ui.Modal, title="➕ เพิ่มรายการการบ้าน"):
    title_input = ui.TextInput(label="ชื่อวิชา / หัวข้อ", placeholder="เช่น คณิตเพิ่มเติม แบบฝึกหัด 1.2", required=True)
    desc_input = ui.TextInput(label="รายละเอียด / คำอธิบาย", style=discord.TextStyle.paragraph, placeholder="เช่น ทำหน้า 10-12 ส่งในระบบ", required=False)
    date_input = ui.TextInput(label="กำหนดส่ง (ปี-เดือน-วัน)", placeholder="เช่น 2026-08-25", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        due_date_str = self.date_input.value.strip()
        
        try:
            datetime.strptime(due_date_str, '%Y-%m-%d')
        except ValueError:
            await interaction.response.send_message("❌ รูปแบบวันที่ไม่ถูกต้อง! ต้องเป็น **ปี-เดือน-วัน** (เช่น `2026-08-25`)", ephemeral=True)
            return

        # 1. บันทึกข้อมูลเข้า Storage Channel (ช่องที่ 3)
        storage_channel = bot.get_channel(STORAGE_CHANNEL_ID) if STORAGE_CHANNEL_ID != 0 else interaction.channel
        
        embed = discord.Embed(
            title=f"📦 [บันทึกการบ้าน] {self.title_input.value}",
            description=self.desc_input.value if self.desc_input.value else "ไม่มีรายละเอียดเพิ่มเติม",
            color=discord.Color.blue()
        )
        embed.add_field(name="📅 กำหนดส่ง", value=due_date_str, inline=True)
        embed.set_footer(text=f"เพิ่มเมื่อ: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        msg = await storage_channel.send(embed=embed)

        # 2. บันทึกลง Database
        conn = sqlite3.connect('homework.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO homework (title, description, due_date, storage_msg_id) VALUES (?, ?, ?, ?)",
            (self.title_input.value, self.desc_input.value, due_date_str, msg.id)
        )
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"✅ บันทึกการบ้าน **{self.title_input.value}** ส่งเข้าคลังเรียบร้อยแล้ว!", ephemeral=True)

# เมนูดรอปดาวน์สำหรับลบการบ้าน (สำหรับช่อง 2 Admin)
class DeleteHomeworkSelect(ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="เลือกการบ้านที่ต้องการลบ...", options=options)

    async def callback(self, interaction: discord.Interaction):
        hw_id = int(self.values[0])
        conn = sqlite3.connect('homework.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT storage_msg_id FROM homework WHERE id = ?", (hw_id,))
        row = cursor.fetchone()
        
        if row and row[0]:
            try:
                storage_channel = bot.get_channel(STORAGE_CHANNEL_ID)
                if storage_channel:
                    msg = await storage_channel.fetch_message(row[0])
                    await msg.delete()
            except Exception as e:
                print(f"ไม่สามารถลบข้อความใน Storage: {e}")

        cursor.execute("DELETE FROM homework WHERE id = ?", (hw_id,))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"🗑️ ลบการบ้านเรียบร้อยแล้ว!", ephemeral=True)

class DeleteHomeworkView(ui.View):
    def __init__(self, options):
        super().__init__(timeout=60)
        self.add_item(DeleteHomeworkSelect(options))

# ปุ่มแผงควบคุม Admin (ช่องที่ 2)
class AdminPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="➕ เพิ่มรายการการบ้าน", style=discord.ButtonStyle.success, custom_id="btn_admin_add")
    async def add_hw(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(AddHomeworkModal())

    @ui.button(label="🗑️ ลบรายการการบ้าน", style=discord.ButtonStyle.danger, custom_id="btn_admin_del")
    async def delete_hw(self, interaction: discord.Interaction, button: ui.Button):
        conn = sqlite3.connect('homework.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, due_date FROM homework ORDER BY due_date ASC")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("❌ ไม่มีรายการการบ้านในระบบ", ephemeral=True)
            return

        options = [
            discord.SelectOption(
                label=f"ID: {row[0]} - {row[1][:25]}",
                description=f"ส่งวันที่: {row[2]}",
                value=str(row[0])
            ) for row in rows[:25]
        ]

        view = DeleteHomeworkView(options)
        await interaction.response.send_message("เลือกการบ้านที่ต้องการลบ:", view=view, ephemeral=True)

# ปุ่มแผงควบคุมสำหรับสมาชิก (ช่องที่ 1 - แสดงผลเฉพาะคนที่กดแบบ Ephemeral)
class MemberPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="📋 ดูรายการการบ้านทั้งหมด", style=discord.ButtonStyle.primary, custom_id="btn_member_view")
    async def view_hw(self, interaction: discord.Interaction, button: ui.Button):
        conn = sqlite3.connect('homework.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, description, due_date FROM homework ORDER BY due_date ASC")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("🎉 ขณะนี้ไม่มีการบ้านค้างอยู่ครับ!", ephemeral=True)
            return

        embed = discord.Embed(title="📝 รายการการบ้านปัจจุบัน", color=discord.Color.green())
        for row in rows:
            desc = f"รายละเอียด: {row[2]}\n" if row[2] else ""
            embed.add_field(
                name=f"🔹 {row[1]}",
                value=f"{desc}📅 กำหนดส่ง: **{row[3]}**",
                inline=False
            )
        # ephemeral=True เพื่อให้เห็นแค่คนที่กดปุ่มคนเดียว คนอื่นมองไม่เห็น และไม่ทำให้แชทรก
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    print(f'บอท {bot.user.name} ออนไลน์แล้ว!')

# ==================== SLASH COMMANDS ====================

@bot.tree.command(name="setup_admin", description="สร้างแผงควบคุมสำหรับ Admin (ใช้ในช่อง Admin)")
async def setup_admin(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ แผงจัดการการบ้าน (สำหรับผู้ดูแล)",
        description="กดปุ่มด้านล่างเพื่อเพิ่ม หรือลบรายการการบ้าน\nข้อมูลจะถูกบันทึกลงคลังและอัปเดตอัตโนมัติ",
        color=discord.Color.red()
    )
    await interaction.channel.send(embed=embed, view=AdminPanelView())
    await interaction.response.send_message("✅ สร้างแผง Admin เรียบร้อย!", ephemeral=True)

@bot.tree.command(name="setup_view", description="สร้างแผงสำหรับสมาชิกเช็กการบ้าน (ใช้ในช่องสมาชิก)")
async def setup_view(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📌 ระบบเช็กการบ้าน",
        description="กดปุ่มด้านล่างเพื่อดูรายการการบ้านทั้งหมดที่ค้างอยู่",
        color=discord.Color.blue()
    )
    await interaction.channel.send(embed=embed, view=MemberPanelView())
    await interaction.response.send_message("✅ สร้างแผงสำหรับสมาชิกเรียบร้อย!", ephemeral=True)

# ==================== AI MENTION SYSTEM ====================
def ask_groq(user_question):
    if not groq_client:
        return "❌ บอทยังไม่ได้ตั้งค่าคีย์ AI"
    prompt = f"คุณคือบอทผู้ช่วยทำการบ้านใน Discord จงตอบคำถามนี้อย่างกระชับ เข้าใจง่าย: {user_question}"
    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
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
                    await message.reply(f"❌ ระบบ AI ขัดข้อง: {e}")

    await bot.process_commands(message)

# ==================== START BOT ====================
if __name__ == '__main__':
    keep_alive()
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)

