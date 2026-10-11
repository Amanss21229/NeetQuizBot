"""
promo_studio.py  -  Alag file. main.py ko bilkul touch nahi karti.

NAYA POST BANANE KA TARIKA:
    Neeche POSTS dict mein ek nayi entry copy-paste karo, text/buttons badlo,
    bot restart karo. Bas. Koi aur code nahi badalna.

ADMIN COMMANDS (sirf bot admins, sirf private chat):
    /promo          -> saare posts ki list
    /promo ai       -> "ai" post ka animated preview (sirf aapko dikhega)
                       + [Send to ALL users] / [Cancel] buttons

NOTE:
    - Animation (line by line typing) sirf preview mein hota hai.
      Users ko broadcast mein ek sundar static message jata hai (effect + buttons),
      kyunki 10k users ko edit-animation bhejna Telegram limits tod dega.
    - Broadcast background mein chalta hai, bot beech mein freeze nahi hota.
    - Broadcast speed ~25 msg/sec (Telegram ki safe limit ke andar).
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from models import db

logger = logging.getLogger(__name__)

BOT_LINK = "https://t.me/DrQuizRobot"

# Telegram ke built-in message effects (sirf private chats mein chalte hain)
EFFECTS = {
    "fire": "5104841245755180586",      # 🔥
    "confetti": "5046509860389126442",  # 🎉
    "heart": "5044134455711629726",     # ❤️
    "like": "5107584321108051014",      # 👍
}


def share_url(text: str) -> str:
    """Telegram share link: user dosto ko ek tap mein forward kar sake."""
    return f"https://t.me/share/url?url={quote(BOT_LINK)}&text={quote(text)}"


# =====================================================================
#  POSTS  -  yahan naye posts add karo
# =====================================================================
# Har post ke fields:
#   title    : sirf aapke liye naam (list mein dikhta hai)
#   effect   : "fire" / "confetti" / "heart" / "like" / None
#   intro    : upar ka headline (HTML allowed: <b>, <i>, <u>, <code>, <tg-spoiler>)
#   points   : bullet lines (broadcast mein tap-to-expand quote ban jaati hain)
#   outro    : neeche ki line
#   buttons  : [[ ("Button text", "https://url") , ... ], ...]  (har inner list = ek row)
#   media    : optional  {"type": "photo" ya "video", "file_id": "..."}  (caption 1024 char tak)

POSTS = {
    "ai": {
        "title": "/ai launch post",
        "effect": "fire",
        "intro": (
            "🤖 𝗡𝗮𝘆𝗮 𝗙𝗲𝗮𝘁𝘂𝗿𝗲: /Ai 𝗶𝘀 𝗟𝗜𝗩𝗘! 🚀\n"
            "Aʙ DʀQᴜɪᴢRᴏʙᴏᴛ ᴘᴇ ᴍɪʟᴇɢᴀ ᴀᴀᴘᴋᴀ ᴀᴘɴᴀ AI ᴅᴏsᴛ + ᴍᴇɴᴛᴏʀ, 24×7 💙"
        ),
        "points": [
            "📚 Sᴛᴜᴅʏ ʜᴇʟᴘ ᴀᴜʀ ᴅᴏᴜʙᴛs ᴄʟᴇᴀʀ",
            "📝 Kɪsɪ ʙʜɪ ᴛᴏᴘɪᴄ ᴋᴇ sʜᴏʀᴛ ɴᴏᴛᴇs",
            "🎯 Kᴜᴄʜ ʙʜɪ ɴᴀʏᴀ sᴇᴇᴋʜɴᴀ",
            "🧭 Cᴀʀᴇᴇʀ ɢᴜɪᴅᴀɴᴄᴇ ᴀᴜʀ ᴍᴇɴᴛᴏʀsʜɪᴘ",
            "💭 Oᴠᴇʀᴛʜɪɴᴋɪɴɢ, sᴛʀᴇss ʏᴀ ᴀᴋᴇʟᴀᴘᴀɴ ᴍᴇɪɴ ʙᴀᴀᴛ ᴋᴀʀɴᴀ",
            "🩺 Hᴇᴀʟᴛʜ ᴀᴜʀ sᴇx ᴇᴅᴜᴄᴀᴛɪᴏɴ ᴋɪ sᴀʜɪ ᴊᴀᴀɴᴋᴀʀɪ",
            "🚫 Bᴜʀᴇ ʜᴀʙɪᴛs sᴇ ʙᴀʜᴀʀ ɴɪᴋᴀʟɴᴇ ᴍᴇɪɴ sᴜᴘᴘᴏʀᴛ",
        ],
        "outro": (
            "Bᴀs ᴛʏᴘᴇ ᴋᴀʀᴏ 👉 /Ai ᴀᴜʀ sʜᴜʀᴜ ʜᴏ ᴊᴀᴏ!\n"
            "🔒 Aᴀᴘᴋɪ ʙᴀᴀᴛᴇɪɴ ᴘʀɪᴠᴀᴛᴇ ʜᴀɪɴ.\n\n"
            "ℹ️ <i>AI doctor ya counsellor nahi hai. Bahut zyada pareshan ho to "
            "kisi apne se ya Tele-MANAS (14416) pe baat karo.</i>"
        ),
        "buttons": [
            [("𝗧𝗥𝗬 𝗡𝗘𝗪 𝗙𝗘𝗔𝗧𝗨𝗥𝗘 🚀",
              "https://t.me/DrQuizRobot?text=Create_a_timetable_for_neet2027")],
        ],
    },

    # ---- NAYA POST: neeche wali entry copy karke naam badlo (example) ----
    # "newbatch": {
    #     "title": "Naya batch announce",
    #     "effect": "confetti",
    #     "intro": "🎉 <b>Rajendra Nagar branch: Early-bird batch open!</b>",
    #     "points": ["✅ Pehle 50 students ko fees mein discount", "✅ Experienced teachers"],
    #     "outro": "Seats limited hain 👇",
    #     "buttons": [[("📞 Admission ke liye DM", "https://t.me/FounderOfLET")]],
    # },
}

# /start <naam> deep-link  ->  bot ka kaunsa function chale
# register() mein bhara jaata hai (ai -> existing /ai command)
DEEPLINKS: dict = {}


# =====================================================================
#  Internal helpers (inhe badalne ki zarurat nahi)
# =====================================================================
_background_tasks: set = set()   # tasks ko garbage-collect hone se bachane ke liye
_sending = {"active": False}     # ek time pe sirf ek broadcast


def _keyboard(post: dict):
    rows = post.get("buttons") or []
    if not rows:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, url=url) for text, url in row] for row in rows]
    )


def _static_text(post: dict) -> str:
    parts = [post["intro"]]
    pts = post.get("points") or []
    if pts:
        parts.append("<blockquote expandable>" + "\n".join(pts) + "</blockquote>")
    if post.get("outro"):
        parts.append(post["outro"])
    return "\n\n".join(parts)


def _animation_steps(post: dict) -> list:
    """Line-by-line reveal ke steps (plain text, last mein static version aata hai)."""
    steps = [post["intro"]]
    steps += list(post.get("points") or [])
    if post.get("outro"):
        steps.append(post["outro"])
    return steps


async def _send_post(bot, chat_id: int, post: dict):
    """Ek user ko post bhejo (effect fail ho to bina effect ke retry)."""
    text = _static_text(post)
    markup = _keyboard(post)
    effect = EFFECTS.get(post.get("effect") or "")
    media = post.get("media")

    async def _once(with_effect: bool):
        kwargs = dict(chat_id=chat_id, parse_mode=ParseMode.HTML, reply_markup=markup)
        if with_effect and effect:
            kwargs["message_effect_id"] = effect
        if media and media.get("type") == "photo":
            return await bot.send_photo(photo=media["file_id"], caption=text, **kwargs)
        if media and media.get("type") == "video":
            return await bot.send_video(video=media["file_id"], caption=text, **kwargs)
        kwargs["link_preview_options"] = LinkPreviewOptions(is_disabled=True)
        return await bot.send_message(text=text, **kwargs)

    try:
        return await _once(True)
    except BadRequest as e:
        if effect and "effect" in str(e).lower():
            return await _once(False)
        raise


async def _animated_preview(bot, chat_id: int, post: dict):
    """Admin ke liye: typing wali animation, phir final static post."""
    steps = _animation_steps(post)
    await bot.send_chat_action(chat_id, ChatAction.TYPING)
    await asyncio.sleep(0.8)

    text = steps[0]
    msg = await bot.send_message(
        chat_id, text, parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    for step in steps[1:]:
        await asyncio.sleep(1.2)  # isse kam mat karo (flood limit)
        text += "\n" + step
        try:
            await msg.edit_text(
                text, parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
    await asyncio.sleep(1.0)
    # Finale: expandable quote + buttons
    await msg.edit_text(
        _static_text(post), parse_mode=ParseMode.HTML, reply_markup=_keyboard(post),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


class _RateGate:
    """Sab sends ke beech minimum gap rakhta hai (Telegram limit ~30/sec)."""

    def __init__(self, per_second: float):
        self.gap = 1.0 / per_second
        self.next = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            t = max(now, self.next)
            self.next = t + self.gap
            if t > now:
                await asyncio.sleep(t - now)


async def _broadcast(bot, admin_chat_id: int, status_msg, post: dict):
    sent = blocked = failed = 0
    try:
        users = await db.get_all_users()
        ids = [u["id"] for u in users]
        total = len(ids)
        gate = _RateGate(25)
        sem = asyncio.Semaphore(20)
        done = 0

        async def worker(uid: int):
            nonlocal sent, blocked, failed, done
            async with sem:
                await gate.wait()
                for attempt in range(2):
                    try:
                        await _send_post(bot, uid, post)
                        sent += 1
                        break
                    except RetryAfter as e:
                        await asyncio.sleep(e.retry_after + 1)
                    except (Forbidden, BadRequest):
                        blocked += 1   # user ne bot block kiya / chat nahi mili
                        break
                    except TelegramError:
                        failed += 1
                        break
                else:
                    failed += 1
                done += 1

        async def progress():
            while done < total:
                await asyncio.sleep(20)
                try:
                    await status_msg.edit_text(
                        f"📤 Sending...\n{done}/{total}\n✅ {sent}  🚫 {blocked}  ⚠️ {failed}"
                    )
                except TelegramError:
                    pass

        ptask = asyncio.create_task(progress())
        await asyncio.gather(*(worker(uid) for uid in ids))
        ptask.cancel()

        await status_msg.edit_text(
            "✅ Promo broadcast complete!\n\n"
            f"👥 Total users: {total}\n"
            f"✅ Delivered: {sent}\n"
            f"🚫 Blocked/unreachable: {blocked}\n"
            f"⚠️ Other errors: {failed}"
        )
    except Exception:
        logger.exception("promo broadcast failed")
        try:
            await status_msg.edit_text(
                f"❌ Broadcast beech mein ruk gaya.\n✅ {sent} users ko ja chuka hai."
            )
        except TelegramError:
            pass
    finally:
        _sending["active"] = False


async def _is_admin(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    return bool(user and chat and chat.type == "private" and await db.is_admin(user.id))


# =====================================================================
#  Handlers
# =====================================================================
async def promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _is_admin(update):
        return  # non-admin ko kuch mat dikhao

    args = context.args or []
    if not args:
        lines = ["🎬 <b>Promo Studio</b>\n"]
        for key, p in POSTS.items():
            lines.append(f"• <code>/promo {key}</code> - {p.get('title', key)}")
        lines.append("\nPost chuno, preview dekho, phir confirm karke sabko bhejo.")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    key = args[0].lower()
    post = POSTS.get(key)
    if not post:
        await update.message.reply_text("❌ Aisa post nahi mila. /promo se list dekho.")
        return

    await update.message.reply_text("👀 Preview (sirf aapko dikh raha hai):")
    await _animated_preview(context.bot, update.effective_chat.id, post)

    confirm = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Send to ALL users", callback_data=f"promo_send:{key}"),
        InlineKeyboardButton("❌ Cancel", callback_data="promo_no"),
    ]])
    await update.message.reply_text(
        "Sab users ko bhejna hai? Ye wapas nahi liya ja sakta.", reply_markup=confirm
    )


async def promo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = update.effective_user
    try:
        if not user or not await db.is_admin(user.id):
            await q.answer("Sirf admin.", show_alert=True)
            return

        if q.data == "promo_no":
            await q.answer("Cancelled")
            await q.edit_message_text("❌ Cancelled. Kuch nahi bheja gaya.")
            return

        key = q.data.split(":", 1)[1]
        post = POSTS.get(key)
        if not post:
            await q.answer("Post nahi mila.", show_alert=True)
            return
        if _sending["active"]:
            await q.answer("Ek broadcast pehle se chal raha hai.", show_alert=True)
            return

        _sending["active"] = True
        await q.answer("Sending shuru...")
        status = await q.edit_message_text("📤 Sending shuru ho raha hai...")
        task = asyncio.create_task(
            _broadcast(context.bot, update.effective_chat.id, status, post)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    finally:
        # main.py ka generic callback handler is button pe dobara na chale
        raise ApplicationHandlerStop


async def deeplink_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start ai  ->  seedha /ai khol do. Baaki /start ko main.py hi sambhalega."""
    if not context.args or not update.message:
        return
    handler = DEEPLINKS.get(context.args[0].lower())
    if handler is None:
        return  # koi aur payload: main.py ka start_command chalega
    await handler(update, context)
    raise ApplicationHandlerStop


# =====================================================================
#  Plugin entry point
# =====================================================================
def register(bot_instance):
    """
    start_with_promo.py isse call karta hai. bot_instance = NEETQuizBot object.
    Handlers group -2 mein jaate hain, taaki main.py ke handlers se pehle chalen
    aur unse takrayen nahi.
    """
    app = bot_instance.application

    # "Start /ai" button: /start ai -> existing /ai command
    ai_handler = getattr(bot_instance, "private_ai_start", None)
    if ai_handler:
        DEEPLINKS["ai"] = ai_handler

    app.add_handler(CommandHandler("promo", promo_command), group=-2)
    app.add_handler(CallbackQueryHandler(promo_callback, pattern=r"^promo_(send:|no$)"), group=-2)
    app.add_handler(CommandHandler("start", deeplink_start), group=-2)
    logger.info("promo_studio loaded: %d post(s)", len(POSTS))
