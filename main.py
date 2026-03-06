import asyncio
import asyncpg
import json
import logging
import os
import time
import threading
from datetime import datetime, timezone
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat, Poll, InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument, InlineQueryResultArticle, InputTextMessageContent, InlineQueryResultCachedPhoto, InlineQueryResultCachedVideo, InlineQueryResultCachedAudio, InlineQueryResultCachedDocument, InlineQueryResultCachedGif, InlineQueryResultCachedVoice, InlineQueryResultCachedSticker
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, PollAnswerHandler, ContextTypes, filters, ChatMemberHandler, InlineQueryHandler
from flask import Flask
from deep_translator import GoogleTranslator
from urllib.parse import quote

# Constants
ADMIN_GROUP_ID = -1003009412065
TIMEZONE = pytz.timezone('Asia/Kolkata')
OWNER_ID = 8147394357

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=5000)

class Database:
    def __init__(self):
        self.pool = None

    async def init(self):
        try:
            self.pool = await asyncpg.create_pool(
                os.environ.get("DATABASE_URL"),
                min_size=1,
                max_size=5,
                max_inactive_connection_lifetime=30
            )
            await self.create_tables()
        except Exception as e:
            logger.error(f"Database init error: {e}")

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    total_score INTEGER DEFAULT 0,
                    correct_answers INTEGER DEFAULT 0,
                    wrong_answers INTEGER DEFAULT 0,
                    unattempted INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    promoted_by BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                INSERT INTO admins (user_id, username, first_name, promoted_by)
                VALUES (8147394357, 'aimforaiims007', 'Aman', 8147394357)
                ON CONFLICT (user_id) DO NOTHING;
                CREATE TABLE IF NOT EXISTS button_posts (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    text TEXT,
                    buttons JSONB NOT NULL,
                    content_type TEXT DEFAULT 'text',
                    file_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

    async def is_admin(self, user_id):
        if not self.pool: return False
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT 1 FROM admins WHERE user_id = $1", user_id) is not None

    async def add_user(self, user_id, username, first_name, last_name):
        if not self.pool: return
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (id, username, first_name, last_name, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (id) DO UPDATE SET username=$2, first_name=$3, last_name=$4, updated_at=NOW()
            """, user_id, username, first_name, last_name)

db = Database()

class NEETQuizBot:
    def __init__(self):
        self.token = os.environ.get("BOT_TOKEN")
        self.application = ApplicationBuilder().token(self.token).build()

    async def initialize(self):
        await db.init()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("CreateButtonPost", self.create_button_post_command))
        self.application.add_handler(CommandHandler("mypost", self.my_posts_command))
        self.application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, self.handle_post_input))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        self.application.add_handler(InlineQueryHandler(self.inline_query))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await db.add_user(user.id, user.username, user.first_name, user.last_name)
        await update.message.reply_text(
            f"👋 **Welcome {user.first_name}!**\n\n"
            "I am the **NEET Quiz Premium Bot**. I can help you create professional posts with custom buttons and manage quizzes.\n\n"
            "🚀 **Ready to create?** Use /CreateButtonPost\n"
            "📂 **Manage your posts?** Use /mypost",
            parse_mode='Markdown'
        )

    async def my_posts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != 'private':
            await update.message.reply_text("❌ Please use this command in private chat.")
            return
        
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, text, content_type FROM button_posts WHERE user_id = $1 ORDER BY created_at DESC LIMIT 10", update.effective_user.id)
        
        if not rows:
            await update.message.reply_text("📭 You haven't created any posts yet. Use /CreateButtonPost to start!")
            return
        
        text = "📂 **YOUR RECENT POSTS**\n\nSelect a post to manage:"
        keyboard = []
        for r in rows:
            preview = (r['text'][:30] + "...") if r['text'] and len(r['text']) > 30 else (r['text'] or f"Post #{r['id']}")
            keyboard.append([InlineKeyboardButton(f"📝 {preview}", callback_data=f"manage_{r['id']}")])
        
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def create_button_post_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != 'private':
            keyboard = [[InlineKeyboardButton("🛠 Create Post Now", url=f"https://t.me/{context.bot.username}?start=create_post")]]
            await update.message.reply_text("💡 **Private Access Required**\nPlease use my private chat for post creation.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return
        
        await update.message.reply_text(
            "💎 **PREMIUM POST CREATOR** 💎\n\n"
            "**Step 1: Send Your Content**\n"
            "Send anything: Text, HD Photo, Video, Audio, File, or Sticker.\n\n"
            "👇 *Drop your content here:*", 
            parse_mode='Markdown'
        )
        context.user_data['creating_post'] = True
        context.user_data['post_step'] = 'content'

    async def handle_post_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get('creating_post'): return
        step = context.user_data.get('post_step')
        
        if step == 'content':
            msg = update.message
            data = {}
            if msg.text: data = {'type': 'text', 'val': msg.text}
            elif msg.photo: data = {'type': 'photo', 'val': msg.photo[-1].file_id, 'txt': msg.caption or ""}
            elif msg.video: data = {'type': 'video', 'val': msg.video.file_id, 'txt': msg.caption or ""}
            elif msg.document: data = {'type': 'document', 'val': msg.document.file_id, 'txt': msg.caption or ""}
            elif msg.sticker: data = {'type': 'sticker', 'val': msg.sticker.file_id}
            elif msg.animation: data = {'type': 'animation', 'val': msg.animation.file_id, 'txt': msg.caption or ""}
            elif msg.audio: data = {'type': 'audio', 'val': msg.audio.file_id, 'txt': msg.caption or ""}
            elif msg.voice: data = {'type': 'voice', 'val': msg.voice.file_id, 'txt': msg.caption or ""}
            else: return await update.message.reply_text("❌ **Unsupported format!** Please send valid media.")
            
            context.user_data.update(data)
            context.user_data['post_step'] = 'buttons'
            await update.message.reply_text(
                "✨ **Step 2: Add Action Buttons**\n\n"
                "Format: `Button Name | URL | Color` (One per line)\n"
                "Colors: `blue`, `red`, `yellow`, `green` (Optional)\n\n"
                "**Example:**\n"
                "Join | https://t.me/FounderOfSansa | blue\n"
                "Support | https://youtube.com/@Sansalearn | red\n\n"
                "⏩ Send /skip if you don't want any buttons.",
                parse_mode='Markdown'
            )
            
        elif step == 'buttons':
            buttons = []
            if update.message.text and update.message.text.lower() != '/skip':
                for line in update.message.text.split('\n'):
                    if '|' in line:
                        p = [x.strip() for x in line.split('|')]
                        if len(p) >= 2:
                            btn = {'text': p[0], 'url': p[1]}
                            if len(p) >= 3:
                                color_map = {
                                    'blue': '🟦', 
                                    'red': '🟥', 
                                    'yellow': '🟨', 
                                    'green': '🟩'
                                }
                                color_key = p[2].lower()
                                if color_key in color_map:
                                    btn['text'] = f"{color_map[color_key]} {btn['text']} {color_map[color_key]}"
                            buttons.append(btn)
            
            async with db.pool.acquire() as conn:
                pid = await conn.fetchval(
                    "INSERT INTO button_posts (user_id, text, buttons, content_type, file_id) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                    update.effective_user.id, 
                    context.user_data.get('txt', context.user_data.get('val', '')), 
                    json.dumps(buttons), 
                    context.user_data['type'], 
                    context.user_data.get('val') if context.user_data['type'] != 'text' else None
                )
            
            # Use self.application.bot.send_message or similar since context.bot might be preferred
            await self.show_post_preview_internal(update, context, pid)
            context.user_data.clear()

    async def show_post_preview_internal(self, update: Update, context: ContextTypes.DEFAULT_TYPE, pid: int):
        async with db.pool.acquire() as conn:
            r = await conn.fetchrow("SELECT * FROM button_posts WHERE id = $1", pid)
        
        if not r: return
        
        buttons_list = json.loads(r['buttons'])
        kb = [[InlineKeyboardButton(b['text'], url=b['url'])] for b in buttons_list]
        kb.append([InlineKeyboardButton("📤 Share Post", switch_inline_query=f"post_{pid}")])
        kb.append([InlineKeyboardButton("🚀 Promote Post", callback_data=f"promote_{pid}")])
        rm = InlineKeyboardMarkup(kb)
        
        t, v, ct = r['text'], r['file_id'], r['content_type']
        cid = update.effective_chat.id
        
        # Determine if we have a message to reply to or a callback to edit
        # For preview via /mypost (callback), we want to send a fresh message after deleting the management one
        # The calling method handles the deletion/answering
        
        try:
            await context.bot.send_message(cid, f"✅ **Post Preview (ID: {pid})**", parse_mode='Markdown')
            
            if ct == 'text': await context.bot.send_message(cid, t, reply_markup=rm, parse_mode='Markdown')
            elif ct == 'photo': await context.bot.send_photo(cid, v, caption=t, reply_markup=rm, parse_mode='Markdown')
            elif ct == 'video': await context.bot.send_video(cid, v, caption=t, reply_markup=rm, parse_mode='Markdown')
            elif ct == 'document': await context.bot.send_document(cid, v, caption=t, reply_markup=rm, parse_mode='Markdown')
            elif ct == 'sticker': await context.bot.send_sticker(cid, v, reply_markup=rm)
            elif ct == 'animation': await context.bot.send_animation(cid, v, caption=t, reply_markup=rm, parse_mode='Markdown')
            elif ct == 'audio': await context.bot.send_audio(cid, v, caption=t, reply_markup=rm, parse_mode='Markdown')
            elif ct == 'voice': await context.bot.send_voice(cid, v, caption=t, reply_markup=rm, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Preview error: {e}")
            await context.bot.send_message(cid, f"✅ Saved! (ID: {pid}). Preview error, but sharing will work.", reply_markup=rm)

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        try:
            await q.answer()
        except: pass
        
        data = q.data
        if data.startswith("promote_"):
            pid = data.split('_')[1]
            kb = [[InlineKeyboardButton("💎 Standard (₹99)", url=f"https://t.me/SansaAdsBot?start={quote(f'Standard Post {pid}')}")],
                  [InlineKeyboardButton("🔥 Mega (₹149)", url=f"https://t.me/SansaAdsBot?start={quote(f'Mega Post {pid}')}")],
                  [InlineKeyboardButton("👑 Ultimate (₹299)", url=f"https://t.me/SansaAdsBot?start={quote(f'Ultimate Post {pid}')}")],
                  [InlineKeyboardButton("🔙 Back", callback_data=f"manage_{pid}")]]
            await q.edit_message_text(
                "🚀 **PREMIUM BOOST OPTIONS**\n\n"
                "Get your post noticed by 50,000+ medical students instantly!\n\n"
                "Select a plan:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='Markdown'
            )
        elif data.startswith("manage_"):
            pid = int(data.split('_')[1])
            kb = [
                [InlineKeyboardButton("👁 Preview", callback_data=f"preview_{pid}")],
                [InlineKeyboardButton("🚀 Promote", callback_data=f"promote_{pid}")],
                [InlineKeyboardButton("🗑 Delete", callback_data=f"delete_{pid}")],
                [InlineKeyboardButton("🔙 Back to List", callback_data="list_posts")]
            ]
            await q.edit_message_text(f"🛠 **Post Management (ID: {pid})**\n\nChoose an action:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        elif data == "list_posts":
            async with db.pool.acquire() as conn:
                rows = await conn.fetch("SELECT id, text FROM button_posts WHERE user_id = $1 ORDER BY created_at DESC LIMIT 10", q.from_user.id)
            if not rows:
                await q.edit_message_text("📭 No posts found.")
                return
            kb = [[InlineKeyboardButton(f"📝 {r['text'][:30]}...", callback_data=f"manage_{r['id']}")] for r in rows]
            await q.edit_message_text("📂 **YOUR RECENT POSTS**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        elif data.startswith("delete_"):
            pid = int(data.split('_')[1])
            async with db.pool.acquire() as conn:
                await conn.execute("DELETE FROM button_posts WHERE id = $1 AND user_id = $2", pid, q.from_user.id)
            await q.answer("✅ Post deleted successfully!", show_alert=True)
            await q.edit_message_text("✅ Post has been deleted.")
        elif data.startswith("preview_"):
            pid = int(data.split('_')[1])
            try:
                await q.message.delete()
            except:
                pass
            await self.show_post_preview_internal(update, context, pid)

    async def inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.inline_query.query
        if not q.startswith("post_"): return
        try:
            pid_str = q.split("_")[1]
            if not pid_str.isdigit(): return
            pid = int(pid_str)
            
            async with db.pool.acquire() as conn:
                r = await conn.fetchrow("SELECT * FROM button_posts WHERE id = $1", pid)
            if not r: return
            
            text, ct, fid = r['text'] or "", r['content_type'], r['file_id']
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(b['text'], url=b['url'])] for b in json.loads(r['buttons'])])
            uid = f"p_{pid}"
            res = None
            
            if ct == 'text':
                res = InlineQueryResultArticle(id=uid, title="💎 Premium Post", description=text[:50], input_message_content=InputTextMessageContent(text, parse_mode='Markdown'), reply_markup=kb)
            elif ct == 'photo':
                res = InlineQueryResultCachedPhoto(id=uid, photo_file_id=fid, title="💎 Premium Photo", caption=text, parse_mode='Markdown', reply_markup=kb)
            elif ct == 'video':
                res = InlineQueryResultCachedVideo(id=uid, video_file_id=fid, title="💎 Premium Video", caption=text, parse_mode='Markdown', reply_markup=kb)
            elif ct == 'document':
                res = InlineQueryResultCachedDocument(id=uid, document_file_id=fid, title="💎 Premium File", caption=text, parse_mode='Markdown', reply_markup=kb)
            elif ct == 'animation':
                res = InlineQueryResultCachedGif(id=uid, gif_file_id=fid, title="💎 Premium GIF", caption=text, parse_mode='Markdown', reply_markup=kb)
            elif ct == 'voice':
                res = InlineQueryResultCachedVoice(id=uid, voice_file_id=fid, title="💎 Premium Voice", caption=text, parse_mode='Markdown', reply_markup=kb)
            elif ct == 'audio':
                res = InlineQueryResultCachedAudio(id=uid, audio_file_id=fid, caption=text, parse_mode='Markdown', reply_markup=kb)
            elif ct == 'sticker':
                res = InlineQueryResultCachedSticker(id=uid, sticker_file_id=fid, reply_markup=kb)

            if res:
                await update.inline_query.answer([res], cache_time=0, is_personal=True)
        except Exception as e:
            logger.error(f"Inline error: {e}")

    async def run(self):
        await self.initialize()
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Bot started successfully!")
        await asyncio.Event().wait()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    try:
        asyncio.run(NEETQuizBot().run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
