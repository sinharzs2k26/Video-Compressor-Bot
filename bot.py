"""
code by Saikat bro 
telegram : @saikatrzsian
"""

import os
import time
import asyncio
import math
import shutil
from datetime import datetime, timedelta
from aiohttp import web
from virtues import idle
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.errors import FloodWait

# --- CONFIGURATION ---
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [7728700576, 7753358925]

# Directories
DOWNLOAD_DIR = "./downloads/"
TEMP_DIR = "./temp/"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# In-memory storage for user states
# { user_id: { "video": path, "thumb": path, "msg_id": int, "task": bool } }
user_data = {}

# --- HELPER FUNCTIONS ---
def to_small_caps(text):
    """Converts text to small caps unicode characters."""
    chars = "abcdefghijklmnopqrstuvwxyz"
    small_caps = "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"
    table = str.maketrans(chars, small_caps)
    return text.translate(table)

def humanbytes(size):
    if not size: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0

async def progress_bar(current, total, text, message, start_time):
    now = time.time()
    diff = now - start_time
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        time_to_completion = round((total - current) / speed) if speed > 0 else 0
        estimated_total_time = round(diff + time_to_completion)

        progress = "[{0}{1}]".format(
            ''.join(["■" for i in range(math.floor(percentage / 10))]),
            ''.join(["□" for i in range(10 - math.floor(percentage / 10))])
        )

        # Using HTML tags here
        tmp = f"{text}\n<code>{progress}</code> <b>{round(percentage, 2)}%</b>\n" \
              f"<b>Size:</b> {humanbytes(current)} / {humanbytes(total)}\n" \
              f"<b>Speed:</b> {humanbytes(speed)}/s\n" \
              f"<b>ETA:</b> {str(timedelta(seconds=time_to_completion))}"
        
        try:
            await message.edit_text(tmp)
        except:
            pass

async def run_ffmpeg(command):
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout, stderr

async def clean_old_files():
    """Background task to delete files older than 30 minutes."""
    while True:
        now = time.time()
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            for f in files:
                path = os.path.join(root, f)
                if os.stat(path).st_mtime < now - 1800:
                    try: os.remove(path)
                    except: pass
        await asyncio.sleep(600)

# --- BOT HANDLERS ---
# Enable HTML parsing globally
app = Client("VideoSensiBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, parse_mode=enums.ParseMode.HTML)

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    header = to_small_caps("Welcome to VideoSensi Compression Bot!")
    await message.reply_text(
        f"<b>{header}</b>\n\n"
        "Send me any video to get started. I can compress large files up to 2GB.\n"
        "You can also send an image to set it as a custom thumbnail.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Join Channel", url="https://t.me/Saikat_RandomZ")
        ]])
    )

@app.on_message(filters.video | filters.document)
async def handle_video(client, message: Message):
    user_id = message.from_user.id
    
    # Check if document is a video
    file = message.video or message.document
    if message.document and not file.mime_type.startswith("video/"):
        return

    if user_id in user_data and user_data[user_id].get("task"):
        return await message.reply_text("⚠️ <b>You already have a task running. Please wait.</b>")

    # Initialize user state
    user_data[user_id] = {
        "video_msg": message,
        "thumb": user_data.get(user_id, {}).get("thumb"), # Preserve existing thumb if any
        "task": False
    }

    buttons = [
        [InlineKeyboardButton("Low Compression", callback_data="comp_low"),
         InlineKeyboardButton("Medium", callback_data="comp_med")],
        [InlineKeyboardButton("High Compression", callback_data="comp_high")],
        [InlineKeyboardButton("Set Thumbnail (Send Image)", callback_data="set_thumb")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_task")]
    ]
    
    label_file = to_small_caps("File Received")
    label_size = to_small_caps("Size")
    
    await message.reply_text(
        f"<b>{label_file}:</b> <code>{file.file_name or 'video.mp4'}</code>\n"
        f"<b>{label_size}:</b> {humanbytes(file.file_size)}\n\n"
        "Choose an action below:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_message(filters.photo)
async def handle_thumb(client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {}
    
    path = os.path.join(DOWNLOAD_DIR, f"thumb_{user_id}.jpg")
    await message.download(file_name=path)
    user_data[user_id]["thumb"] = path
    await message.reply_text("✅ <b>Thumbnail saved!</b> It will be applied to your next compression.")

@app.on_callback_query(filters.regex("^comp_"))
async def compression_callback(client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_data or not user_data[user_id].get("video_msg"):
        return await callback.answer("No active file found. Send the video again.", show_alert=True)

    quality = callback.data.split("_")[1]
    user_data[user_id]["task"] = True
    video_msg = user_data[user_id]["video_msg"]
    
    # Mapping CRF and Bitrates
    configs = {
        "low": {"crf": "30", "preset": "ultrafast", "b_v": "800k"},
        "med": {"crf": "24", "preset": "veryfast", "b_v": "1500k"},
        "high": {"crf": "20", "preset": "medium", "b_v": "3000k"}
    }
    cfg = configs[quality]

    status_msg = await callback.message.edit_text("⏳ <b>Initializing...</b>")
    
    try:
        # 1. Download Video
        start_time = time.time()
        file_path = os.path.join(DOWNLOAD_DIR, f"{user_id}_input.mp4")
        await status_msg.edit_text("📥 <b>Downloading video...</b>")
        
        await video_msg.download(
            file_name=file_path,
            progress=progress_bar,
            progress_args=("📥 <b>Downloading:</b>", status_msg, start_time)
        )

        # 2. Compress Video
        output_path = os.path.join(DOWNLOAD_DIR, f"{user_id}_compressed.mp4")
        await status_msg.edit_text(f"⚙️ <b>Compressing ({quality})... Please wait.</b>")
        
        # Optimized FFmpeg command for mobile-friendly MP4
        ffmpeg_cmd = (
            f'ffmpeg -i "{file_path}" -c:v libx264 -crf {cfg["crf"]} -preset {cfg["preset"]} '
            f'-b:v {cfg["b_v"]} -maxrate {cfg["b_v"]} -bufsize 2M -c:a aac -b:a 128k '
            f'-pix_fmt yuv420p -y "{output_path}"'
        )
        
        rc, _, err = await run_ffmpeg(ffmpeg_cmd)
        if rc != 0:
            raise Exception(f"FFmpeg error: {err.decode()[-200:]}")

        # 3. Upload Video
        await status_msg.edit_text("📤 <b>Uploading...</b>")
        start_time = time.time()
        
        orig_size = os.path.getsize(file_path)
        new_size = os.path.getsize(output_path)
        saving = ((orig_size - new_size) / orig_size) * 100
        
        thumb = user_data[user_id].get("thumb")
        
        header_complete = to_small_caps("Compression Complete")
        label_orig = to_small_caps("Original")
        label_comp = to_small_caps("Compressed")
        label_saved = to_small_caps("Saved")

        await client.send_video(
            chat_id=callback.message.chat.id,
            video=output_path,
            caption=(
                f"✅ <b>{header_complete}!</b>\n\n"
                f"📁 <b>{label_orig}:</b> {humanbytes(orig_size)}\n"
                f"📉 <b>{label_comp}:</b> {humanbytes(new_size)}\n"
                f"✨ <b>{label_saved}:</b> {saving:.1f}%"
            ),
            thumb=thumb,
            progress=progress_bar,
            progress_args=("📤 <b>Uploading:</b>", status_msg, start_time)
        )
        
        await status_msg.delete()

    except Exception as e:
        await callback.message.reply_text(f"❌ <b>Error:</b> <code>{str(e)}</code>")
    finally:
        # Cleanup
        user_data[user_id]["task"] = False
        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(output_path): os.remove(output_path)

@app.on_callback_query(filters.regex("cancel_task"))
async def cancel_callback(client, callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data.pop(user_id, None)
    await callback.message.edit_text("❌ <b>Task cancelled and temporary data cleared.</b>")

@app.on_callback_query(filters.regex("set_thumb"))
async def set_thumb_btn(client, callback: CallbackQuery):
    await callback.answer("Just send me a photo now!", show_alert=True)

# --- STARTUP ---
async def handle(request):
    return web.Response(text="Bot is running!")
    
async def main():
    print("--- VideoSensi Bot Starting ---")
    asyncio.create_task(clean_old_files())
    server = web.Application()
    server.router.add_get("/", handle)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()
    await app.start()
    print("--- Bot is Online ---")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())