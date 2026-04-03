import asyncio
import asyncpg
import json
import logging
import os
import random
from datetime import datetime, timezone, time
from typing import Dict, List

import pytz
from telegram import (
    Bot,
    InputTextMessageContent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultCachedAudio,
    InlineQueryResultCachedDocument,
    InlineQueryResultCachedGif,
    InlineQueryResultCachedVoice,
    InlineQueryResultCachedSticker,
    Update,
    BotCommand,
    BotCommandScopeChat,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaAudio, 
    InputMediaDocument,
    Poll,
    PollAnswer,
    ChatMember,
    Message
)
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application, 
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PollAnswerHandler,
    ChatMemberHandler,
    InlineQueryHandler,
    ContextTypes,
    filters
)
try:
    from telegram.ext import ApplicationHandlerStop
except ImportError:
    ApplicationHandlerStop = None

from models import db
from clone_manager import clone_manager
from flask import Flask
import threading
from deep_translator import GoogleTranslator
from urllib.parse import quote


# Bot configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required. Please set it with your bot token from @BotFather")
ADMIN_GROUP_ID = -1003009412065
TIMEZONE = pytz.timezone('Asia/Kolkata')
OWNER_ID = 8147394357

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------- Render Flask keep-alive (ADD THIS) -----------------
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ NEET Quiz Bot is running!"

def run_flask():
    # Render sets PORT env var automatically; default 5000 for local testing
    port = int(os.environ.get("PORT", 5000))
    # Use host 0.0.0.0 so Render can bind
    app.run(host="0.0.0.0", port=port)
# --------------------------------------------------------------------

# Security: Hide bot token from logs by reducing httpx and telegram logging level
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

# Congratulatory messages for correct answers
CORRECT_MESSAGES = [
    "🔥 You rocked it! +4 points!",
    "🤩 waah re babua, bilkul shi jawaab! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v Sabji laane market jaao, to shopkeeper tumhe Dhaniya Free me de! +4 points!",
    "🎉 Absolutely right! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v Hari Dhaniya laane market jaao, to shopkeeper tumhe Sabji free me dede! +4 points!",
    "😍 ohho ek dam shi jawaab! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v Litti chhola khaane market jaao, to Tumhaara plate me bdi waali little aaye! +4 points!",
    "✨ Brilliant answer! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v Mela Ghumne jaao, to shopkeeper Tumhe free me Jhulua Jhula de! +4 points!",
    "😇 waah bete tune to moj kardi, bilkul shi jawaab! +4 points!",
    "🚀 Outstanding! babua +4 points!",
    "😚 lagta hai delhi aiims jaake hi maanoge beta, bilkul shi jawaab! +4 points!",
    "🏆 Perfect mera munna! +4 points!",
    "🔥 Tune to Aag lga di beta, bilkul shi answer! +4 points!",
    "⭐ Excellent work Mera Babu! +4 points!",
    "🎯 7 crore, bilkul shi jawaab! +4 points!",
    "💯 Spot on! +4 points!",
    "🌟 Amazing! +4 points!",
    "🔥 Aag laga di beta, answer dekh ke NCERT bhi sharma gayi! +4 points!",
    "😏 Doctor material spotted! Crush bhi impress ho gayi hogi! +4 points!",
    "😜 Beta, tumhe dekh ke lagta hai kal rat ko padhai ki thi, timepass nahi! +4 points!",
    "😅 Correct answer! Waise lagta hai guessing queen/king ho tum! +4 points!",
    "💥 shi jawaab Lagta hai tumhare neurons 5G speed pe chal rahe hain! +4 points!",
    "😂 Waah bhai, NCERT tumhe apna best friend banane wali hai! +4 points!",
    "🤩 Sahi jawaab, topper material yahi hai! +4 points!",
    "🥰 Tumne itna awsome answer diya ki mai bhi shock ho gaye! +4 points!",
    "😏 Lagta hai science sirf tumhare liye bani hai! +4 points!",
    "😎 Kya baat hai doctor sahab, sahi jawab dete hi attitude 2x ho gya! +4 points!",
    "😍 Tumhare answer se lagta hai padhai aur pyar dono balance kar lete ho! +4 points!",
    "🫡 Ekdum surgical strike answer tha re! +4 points!",
    "🔥 Tera dimaag Ambani ka Jio tower hai kya? Speed dekhi? +4 points!",
    "😎 Sahi jawab… topper vibes aa rahi hai! +4 points!",
    "🥰 Bot bhi tumpe fida ho gya is answer ke baad! +4 points!",
    "🤯 Bilkul surgical precision! +4 points!",
    "😂 Arey waah, ek baar me sahi kar diya? Salute! +4 points!",
    "😏 Tumhare answer dekh ke lagta hai mummy ne ratta lagwaya hoga! +4 points!",
    "🤪 Sahi jawaab, ab tu NEET ka alpha hai! +4 points!",
    "🤡 Lagta hai tumhare dimaag bilkul doctor ki tarah chal rahe hai, full fast! +4 points!",
    "🥲 Bot ko ab yakeen aa gya ki tum padhte bhi ho! +4 points!",
    "😂 Correct answer, ab mummy bolegi: “Sharma ji ka beta ban gya mera baccha!” +4 points!",
    "❤️ Ye sahi jawab dekh ke lagta hai science tumhare khoon me hai! +4 points!",
    "🤯 Ekdum dhansu reply, teacher bhi impress ho gye honge! +4 points!",
    "😏 Tumhare answer me thodi IQ aur thodi Aashiqui jhalakti hai! +4 points!",
    "😍 Waah bete, ab lagta hai tumhara MBBS confirm hai! +4 points!",
    "😂 Correct answer! Ab galat wale ko bolo “seekh le kuchh!” +4 points!",
    "🔥 Mast reply, option pe click karte hi pura group hil gya! +4 points!",
    "🥳 Tumhare answer se NEET bhi khush ho gya! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v Rausogulla laane market jaao, to shopkeeper tumhe Rausogulla pe Rasmallai Free me dede! +4 points!",
    "😎 Doctor banne ka swag tumhare andar clearly dikhta hai! +4 points!",
    "🥵 Lagta hai tumhare answers NCERT ki asli copy hai! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v samose laane market jaao, to shopkeeper tumhe extra me chatni dede! +4 points!",
    "🤡 Waah bhai, meri dua hai ki tumhe raste pe 7-8 crore gire hue mile! +4 points!",
    "😏 Tumhara correct answer = Bot ka dil garden-garden! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v chhole Bhature khaane market jaao, to shopkeeper tumhe extra me chhole de! +4 points!",
    "🥰 Answer sahi, style bhi sahi… bas crush ko propose kar dena ab! +4 points!",
    "🥹 shi jawaab, Lagta hai tumhaari saadi koi actor/actress se hoga.☺️ Batao kisse karoge saadi?! +4 points!",
    "😎 Bawal kar diya re baba, full respect! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v Pizza Order karo, to tumhe ofder mile, 1 pe 4 pizza free! +4 points!",
    "😎 Shi jawaab,  Uperwala tumhe 1CRORE de! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v samose laane market jaao, to shopkeeper tumhe extra me chatni dede! +4 points!",
    "🤓 Topper Spotted! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v momos laane market jaao, to shopkeeper tumhe extra momos dede! +4 points!",
    "🤯 Jordaar Beta, Is answer ke liye tumhe ek Jordan ka shoes milega but neet me top karne pe, jaake owner se maang lena😌! +4 points!",
    "🤒 Ek no. Beta, kya answer diya hai, isi baat pe jaao biryaani kha lo, or paise owner de dega! +4 points!",
    "🤩 Gazab, Beta Teri ek seat pakki, guarantee mai deta hu! +4 points!",
    "😎 Shi jawaab, meri dua hai ki tum jb v Burger khaane market jaao, to shopkeeper tumhare burger me extra butter daal ke de! +4 points!",
    "😄 Waah Jabardast, Isi baat pe owner or admin ko party dedo! +4 points!",
    "🔥 Fantastic! +4 points!"
]

# Sad/funny messages for wrong answers
WRONG_MESSAGES = [
    "😢 Beda garak, isi baat pe pesh hai ek shayari: Talash Meri Thi, or Bhatak rha tha wo,Dil Mera tha or dhadak rha tha wo.Pyar ka talluk v ajeeb hota hai,Aansu mere the or sisak rha tha wo❤️‍🩹, enjoy kya Kar rhe band karo ye sb or padhai karo buddhu😂😂! -1 point",
    "🤦‍♂️ Padho beta padho! -1 point",
    "😅 Oops! Better luck next time! -1 point",
    "🤧 Galat Hai, koi @admins active hai to ise mere tataf se Prasad dedo👊! -1 points,"
    "💔 So close, yet so far! -1 point",
    "😔 Not quite right! -1 point",
    "🙈 Try again! -1 point",
    "😞 Almost there! -1 point",
    "☻️ sirf reproduction padhne se neet nhi nikala beta🤡! -1 point",     
    "😏 Sirf Manzil ko bhula kar jiya to kya jiya wala motivation sunne se kuchh nhi hoga paglu! -1 point",
    "🤷‍♂️ Galat jawab! -1 point",
    "😵 Wrong choice! -1 point",
    "🤕 Thoda aur mehnat! -1 point",
    "🥲 kyu nhi ho rhi padhai! -1 point",
    "🤒 Dekha Laparwaahi ka naatiza! -1 point",
    "😂 wrong Answer! Itna confidence galat answer me? Mazza aa gya! -1 point",
    "🤦 NEET dene aaye ho ya Splitsvilla audition?, Galat hai ye Answer! -1 point",
    "🙄 wrong Answer! NCERT padhne se zyada toh tumne reels save ki hogi! -1 point",
    "😋 wrong , BTW cute lag rahe ho galti karte hue bhi! -1 point",
    "🤕 Beta tumhare notes chhup ke padosi likh rahi hai kya?! -1 point",
    "🐒 Lagta hai dimaag exam ke bajaye crush pe atka hua hai. Beta! -1 point",
    "💀 Ye answer dekh ke mummy bolegi: ‘Doctor banna hai ya stand-up comedian?’! -1 point",
    "😜 Sahi answer chhod ke galat pe gaye… just like tumhare pichhle relationship me! -1 point",
    "🤡 Tumhare option dekh ke lagta hai NCERT tumse personal dushmani rakhti hai! -1 point",
    "🫢 Acha hua NEET single choice hai, warna tum 4 me se 5 option tick kar dete! -1 point",
    "🤭 Tumhe dekh ke lagta hai MCQ ka matlab hai ‘Mere Confused Questions’! -1 point",
    "😏 Galtiyan bhi tumhari cuteness pe fida ho gayi! -1 point",
    "🙃 Tumhara galat answer bhi itna pyaara hai ki -1 bhi smile de gaya! -1 point",
    "🐔 Lagta hai option choose karte waqt ‘Inky Pinky Ponky’ chal raha tha! -1 point",
    "😏 Answer kaha se shi hoga, Tum to poora din Telegram pe oo ji aho ji karte rehte ho😂! -1 point",
    "🤣 Aapka jawaab galat hai… lekin attitude ekdum topper jaisa! -1 point",
    "🥲 Tumhara galat answer bhi itna confident tha ki mujhe doubt ho gaya! -1 point",
    "😂 Tumhare galat answer dekh ke Munna Bhai MBBS bhi shock ho gaya! -1 point",
    "🤷 Doctor banna tha… comedian ban gaye! -1 point",
    "😏 Lagta hai tumhari padhai ki battery 2% pe chal rahi hai! -1 point",
    "🤣 Tumhara galat answer bhi trending reel ban sakta hai! -1 point",
    "😋 Tumhari galti bhi Instagram story material hai.😂😂! -1 point",
    "😜 Beta, NEET me ye mat bolna ‘Itna toh guess karne ka haq banta hai’.😂! -1 point",
    "🙄 Lagta hai padhai chhod ke tum content creator ban jaoge! -1 point",
    "😭 Tumhare -1 pe mummy ka chappal flying mode me aane wala hai.! -1 point",
    "🫢 Tumhare answer se to lagta hai crush bhi block kar degi.! -1 point",
    "🫠 Bhai tu doctor banega ya RJ Naved?! -1 point",
    "🤔 Lagta hai biology ke bajaye tum botany garden ghoom rahe the. But kiske saath?🙂😁! -1 point",
    "🤣 Tumhe NEET me bonus milega: ‘Best Guess Award’! -1 point",
    "😜 wrong Answer, Lagta hai kal raat me padhai ke bajaye Netflix chala rahe the! -1 point",
    "😅 Oops! Padha tha ya bas reels scroll kiya tha?! -1 point",
    "🤦‍♂️ Beta galat ho gya, padhai pe dhyaan do, pyar baad me! 💔! -1 point",
    "🤡 Wrong answer! Waise Pinky ko impress karne me busy the kya?! -1 point",
    "😭 Arre baba, galti pe galti! -1 point gaya! -1 point",
    "🥲 Kyu itna careless ho? NEET hai, Gudda Gudiya ka khel nhi! -1 point",
    "🤕 Lagta hai ratta fail ho gya beta! -1 point",
    "🥴 Galtiyaan bhi tumse sharma rahi hai beta! -1 point",
    "🙈 Wrong answer, tumse na ho payega bhai! -1 point",
    "🤦 Wrong… lagta hai 'guess' karne wali strategy fail ho gayi! -1 point",
    "🤡 Rattafication failed! -1 mila tumhe! -1 point",
    "💤 Neend me quiz de rahe ho kya? 😪! -1 point",
    "🐒 Lagta hai tum group ka Rajpal Yadav ho 😆! -1 point",
    "😑 Matlab ab tumhe remedial class chahiye! -1 point",
    "💀 RIP 1 point. Tumhari wajah se gaya! -1 point",
    "🧟 Lagta hai tumhe 'wrong answers only' challenge pasand hai! -1 point",
    "🐔 Option mark karte samay chicken dance chal raha tha kya?! -1 point",
    "😂 Ye to Ananya Pandey level ka struggle answer tha! -1 point",
    "🤡 Wrong! Waise guess karne ka career acha rahega! -1 point",
    "🥲 Tumhare dosto ko bata du kya tumhara answer?! -1 point",
    "🐒 Option galat, confidence high — ekdum mast jodi! -1 point",
    "🤦 Lagta hai syllabus chhod ke astrology padh rahe ho! -1 point",
    "🙄 Kya tum option tick karte waqt 'Inky Pinky Ponky' use karte ho ya akar bakar bambe bo?! -1 point",
    "😔 Wrong… ab agle question me sudhar laana padega! -1 point",
    "😋 Ye galti bhi cute hai… par marks cut gaya.! -1 point",
    "🎭 Tumne quiz ko joke samjh liya kya?! -1 point",   
    "😏 Answer kaha se shi hoga, Tum to poora din to Doremon dekhte rehte ho🥲! -1 point",    
    "😌 wrong answer, BTW Tum to one shot waale ho na! -1 point",
    "🙃 Galat jawaab, Or pado pinki ke chakkar me😆! -1 point",
    "👀 jb distraction se dhyaan hatega tabhi to answer shi hoga☻️! -1 point",
    "😶 wrong Answer, btw tum to whi ho na jo tg pe padhne aaye the or study partner dhundne lage🤣! -1 point",
    "😒 kaua udd, chirya udd, padhai udd🙂 Udd gai na padhai🥲 Galat jawaab🤧! -1 point",
    "😒 Keh do ki Tum meri ho warna😉 jeena nhi mujhe hai padhna😅🤣! -1 point",
    "😒 hurr🤧! -1 point",
    "😒 Tum whi ho na jo Galat jawab deke bolte ho, im joking yaar🤧 mujhe aata tha iska answer😅🤣! -1 point",
    "🤭 Laal Phool, Neela Phool🙂 tum to nikle beautifool😜! -1 point",
    "🤐 Galat jawaab, padhle yaara masti me, nhi to saadi hogi chhoti basti me👀! -1 point",
    "🥲 Galat jawaab, Bolo Pencil🙂are bolo🥲! -1 point",
    "😕 Galat jawaab, waise yaara maine suna hu ki tum🤭 chhoro jaane do mai nhi bolunga.😁 menu saram aati hai☺️! -1 point",
    "😒 Galat jawaab, htt burwakwa eho nai aabo hai🤧! -1 point",
    "😐 Galat jawaab, Inqalab zindabaat,✊️ padhai teri jaise jhinga bhaat🤡! -1 point",
    "😒 Galat jawaab, kuchh na kho,🥰👀 or jaake padhai karo😂! -1 point",
    "😒 Galat jawaab, Tum To Dhokebaaz ho😒, Mujhe sb aata hai ye bolke, answer galat kar dete ho.☹️ Roj Roj Tum jo sansam aisa karoge😕😣, yaad rakhna neet exam me haath maloge🥲😅! -1 point",
    "😶 Galat jawaab, saas, bahu, Saazish dekhne se achha hai, practice practice or sirf practice pe dhyaan do😄! -1 point",
    "😐 Galat jawaab, oh Nora Fateh ke Dewaane🤪, padh le yaar😅! -1 point",
    "😏 Galat jawaab, Anupma Hi dekhte rho tum😮‍💨,Tumhaare badle padhai v anupma hi kar legi🥱! -1 point",
    "🤧 Galat jawaab, kumkum bhaag dekh ke rone se achha hai neet nikaalke haso yaara😁! -1 point",
    "🤨 Galat jawaab, Ab mai kuchh bolunga, to bologe Aji gaali deta hai😏🤣 ",
    "😕 Galat jawaab, waise yaara maine suna hu ki tum🤭 chhoro jaane do mai nhi bolunga.😁 menu saram aati hai☺️! -1 point",
    "😕 Galat jawaab, waise yaara maine suna hu ki tum🤭 chhoro jaane do mai nhi bolunga.😁 menu saram aati hai☺️! -1 point",
    "😮‍💨 Wrong answer, waise wo tum hi ho na jo Har group me 'i need study partner' message karta hai😂! -1 point" 
]

class NEETQuizBot:
    def __init__(self):
        self.application = None
        self.quiz_data = {}  # Store active quizzes
        self.poll_mapping = {}  # Store poll_id -> {quiz_id, group_id, message_id}
        self.quiz_mapping = {}  # {forwarded_message_id: quiz_id}
        self.groups_cache = {}  # In-memory cache: {group_id: {"title": str, "type": str}} - works without DB
        self.translation_cache = {}  # Cache translations: {(quiz_id, language): {'question': str, 'options': list}}
        self.broadcast_semaphore = asyncio.Semaphore(25)  # Limit concurrent sends to 25
        self._clone_setup_pending = {}  # {user_id: 'awaiting_token'} for /clone flow
    
    async def _parallel_send(self, send_func, chat_ids: List, status_msg=None, context=None, label="Sending", 
                             track_messages=False, original_message_id=None, original_chat_id=None, sent_by=None):
        """
        High-performance parallel message sender with rate limit handling.
        
        Args:
            send_func: Async function that takes chat_id and returns MessageId object or True/False
            chat_ids: List of chat IDs to send to
            status_msg: Optional status message to update with progress
            context: Bot context for status updates
            label: Label for progress messages
            track_messages: If True, store sent message mappings for /delete command
            original_message_id: Original message ID (required if track_messages=True)
            original_chat_id: Original chat ID (required if track_messages=True)
            sent_by: User ID who sent the broadcast (required if track_messages=True)
        
        Returns:
            Tuple of (success_count, failed_count, results_dict)
        """
        success_count = 0
        failed_count = 0
        results = {'groups': 0, 'channels': 0, 'users': 0, 'failed': 0}
        total = len(chat_ids)
        processed = 0
        last_update = 0
        
        async def send_with_semaphore(chat_info):
            nonlocal success_count, failed_count, processed, last_update, results
            
            async with self.broadcast_semaphore:
                chat_id = chat_info['id'] if isinstance(chat_info, dict) else chat_info
                chat_type = chat_info.get('type', 'user') if isinstance(chat_info, dict) else 'user'
                
                try:
                    # Attempt to send
                    result = await send_func(chat_id)
                    success = result is not None and result is not False
                    if success:
                        success_count += 1
                        if chat_type == 'channel':
                            results['channels'] += 1
                        elif chat_type in ['group', 'supergroup']:
                            results['groups'] += 1
                        else:
                            results['users'] += 1
                        
                        # Track sent message for /delete command
                        if track_messages and original_message_id and original_chat_id:
                            try:
                                sent_msg_id = result.message_id if hasattr(result, 'message_id') else result
                                if isinstance(sent_msg_id, int):
                                    await db.store_sent_message(
                                        original_message_id, original_chat_id,
                                        sent_msg_id, chat_id, sent_by
                                    )
                            except Exception as track_err:
                                logger.debug(f"Failed to track message: {track_err}")
                    else:
                        failed_count += 1
                        results['failed'] += 1
                except Exception as e:
                    error_msg = str(e).lower()
                    # Handle rate limiting with exponential backoff
                    if 'retry after' in error_msg or '429' in error_msg:
                        try:
                            # Extract retry time from error message
                            retry_after = 1
                            if 'retry after' in error_msg:
                                parts = error_msg.split('retry after')
                                if len(parts) > 1:
                                    retry_after = int(''.join(filter(str.isdigit, parts[1][:10]))) or 1
                            await asyncio.sleep(min(retry_after, 5))  # Max 5 seconds wait
                            # Retry once
                            try:
                                result = await send_func(chat_id)
                                success = result is not None and result is not False
                                if success:
                                    success_count += 1
                                    if chat_type == 'channel':
                                        results['channels'] += 1
                                    elif chat_type in ['group', 'supergroup']:
                                        results['groups'] += 1
                                    else:
                                        results['users'] += 1
                                    
                                    # Track sent message for /delete command
                                    if track_messages and original_message_id and original_chat_id:
                                        try:
                                            sent_msg_id = result.message_id if hasattr(result, 'message_id') else result
                                            if isinstance(sent_msg_id, int):
                                                await db.store_sent_message(
                                                    original_message_id, original_chat_id,
                                                    sent_msg_id, chat_id, sent_by
                                                )
                                        except Exception as track_err:
                                            logger.debug(f"Failed to track message: {track_err}")
                                else:
                                    failed_count += 1
                                    results['failed'] += 1
                            except:
                                failed_count += 1
                                results['failed'] += 1
                        except:
                            failed_count += 1
                            results['failed'] += 1
                    else:
                        failed_count += 1
                        results['failed'] += 1
                        logger.debug(f"Send failed to {chat_id}: {e}")
                
                processed += 1
                
                # Update status every 10% or 50 messages
                if status_msg and context and (processed - last_update >= max(total // 10, 50)):
                    last_update = processed
                    progress_pct = int((processed / total) * 100)
                    try:
                        await status_msg.edit_text(
                            f"📡 {label}...\n\n"
                            f"⏳ Progress: {progress_pct}% ({processed}/{total})\n"
                            f"✅ Sent: {success_count}\n"
                            f"❌ Failed: {failed_count}"
                        )
                    except:
                        pass  # Ignore edit errors
        
        # Create all tasks and run them concurrently
        tasks = [send_with_semaphore(chat_info) for chat_info in chat_ids]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        return success_count, failed_count, results
    
    async def check_force_join(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, List[Dict]]:
        """Check if user has joined all force join groups. Returns (is_joined, missing_groups)"""
        force_join_groups = await db.get_force_join_groups()
        if not force_join_groups:
            return True, []
        
        missing_groups = []
        for group in force_join_groups:
            try:
                member = await context.bot.get_chat_member(group['chat_id'], user_id)
                if member.status in ['left', 'kicked']:
                    missing_groups.append(group)
            except Exception as e:
                logger.error(f"Error checking membership for user {user_id} in chat {group['chat_id']}: {e}")
                missing_groups.append(group)
        
        return len(missing_groups) == 0, missing_groups
    
    async def send_force_join_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, missing_groups: List[Dict]):
        """Send polite message with buttons for force join groups"""
        keyboard = []
        for group in missing_groups:
            button_text = group['chat_title'] or group['chat_username'] or f"Join Group {group['chat_id']}"
            if group['invite_link']:
                button_url = group['invite_link']
            elif group['chat_username']:
                button_url = f"https://t.me/{group['chat_username'].replace('@', '')}"
            else:
                continue
            
            keyboard.append([InlineKeyboardButton(f"📢 {button_text}", url=button_url)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = """
🔐 **Access Required**

Hello! To use this bot, you need to join our official groups/channels first.

✨ **Why join?**
• Get instant quiz updates
• Access to exclusive content
• Connect with NEET aspirants community

👇 **Please join all groups below, then try again:**
        """
        
        # Check if update has message (command/text) or poll_answer
        if update.message:
            await update.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            # For poll answers or other updates without message, send directly to user
            await context.bot.send_message(
                chat_id=user_id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    async def initialize(self):
        """Initialize the bot and database"""
        await db.init_pool()
        
        # Create bot application
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        # Add default admin (you can add your user ID here)
        try:
            await db.add_admin(
                user_id=8162524828,  # Add your actual user ID here
                username="indiantguser",
                first_name="Admin"
            )
        except:
            pass  # Admin might already exist
        
        # Register handlers
        self._register_handlers()
        
        # Set bot commands
        await self._set_bot_commands()
        
        # Schedule daily leaderboards at 10:00 PM IST
        self.application.job_queue.run_daily(
            callback=self.send_daily_leaderboards,
            time=time(hour=22, minute=0, tzinfo=TIMEZONE),  # 10:00 PM IST
            name="daily_leaderboards"
        )
        
        # Schedule weekly leaderboard reset every Sunday at 11:59 PM IST
        self.application.job_queue.run_daily(
            callback=self.reset_weekly_leaderboards,
            time=time(hour=23, minute=59, tzinfo=TIMEZONE),  # 11:59 PM IST
            days=(6,),  # Sunday (0=Monday, 6=Sunday)
            name="weekly_reset"
        )
        
        # Schedule daily wrong quiz summary at 10:10 PM IST
        self.application.job_queue.run_daily(
            callback=self.send_daily_wrong_quiz_summary,
            time=time(hour=22, minute=10, tzinfo=TIMEZONE),  # 10:10 PM IST
            name="daily_wrong_quiz_summary"
        )

    
    def _register_handlers(self):
        """Register all bot handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("refresh", self.refresh_command))
        self.application.add_handler(CommandHandler("createbuttonpost", self.create_button_post_command))
        self.application.add_handler(CommandHandler("mypost", self.my_posts_command))        
        self.application.add_handler(CommandHandler("donate", self.donate_command))
        self.application.add_handler(CommandHandler("developer", self.developer_command))
        self.application.add_handler(CommandHandler("myscore", self.myscore_command))
        self.application.add_handler(CommandHandler("mymistake", self.mymistake_command))
        self.application.add_handler(CommandHandler("leaderboard", self.leaderboard_command))
        self.application.add_handler(CommandHandler("sol", self.get_solution))
        self.application.add_handler(CommandHandler("promotion", self.promotion_command))
      
        # Admin commands
        self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
        self.application.add_handler(CommandHandler("pbroadcast", self.pbroadcast_command))
        self.application.add_handler(CommandHandler("gbroadcast", self.gbroadcast_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("promote", self.promote_command))
        self.application.add_handler(CommandHandler("remove", self.remove_command))
        self.application.add_handler(CommandHandler("adminlist", self.adminlist_command))
        self.application.add_handler(CommandHandler("grouplist", self.grouplist_command))
        self.application.add_handler(CommandHandler("setsol", self.set_solution))
        self.application.add_handler(CommandHandler("resetleaderboard", self.reset_leaderboard))
        self.application.add_handler(CommandHandler("addpositivereply", self.add_positive_reply_command))
        self.application.add_handler(CommandHandler("addnegativereply", self.add_negative_reply_command))
        self.application.add_handler(CommandHandler("removereply", self.remove_reply_command))
        self.application.add_handler(CommandHandler("replyoff", self.replyoff_command))
        self.application.add_handler(CommandHandler("replyon", self.replyon_command))
        self.application.add_handler(CommandHandler("language", self.language_command))
        self.application.add_handler(CommandHandler("emergencybroadcast", self.emergency_broadcast_command))
        self.application.add_handler(CommandHandler("ebroadcast", self.emergency_broadcast_command))
        self.application.add_handler(CommandHandler("fjoin", self.fjoin_command))
        self.application.add_handler(CommandHandler("removefjoin", self.removefjoin_command))
        self.application.add_handler(CommandHandler("forward", self.forward_command))
        self.application.add_handler(CommandHandler("clone", self.clone_command))
        self.application.add_handler(CommandHandler("pauseclone", self.pauseclone_command))
        self.application.add_handler(CommandHandler("resumeclone", self.resumeclone_command))
        self.application.add_handler(CommandHandler("clonelist", self.clonelist_command))

        # Poll and quiz handlers
        self.application.add_handler(MessageHandler(filters.POLL, self.handle_quiz))
        self.application.add_handler(MessageHandler(filters.TEXT & filters.REPLY, self.handle_reply_to_poll))
        self.application.add_handler(PollAnswerHandler(self.handle_poll_answer))
        
        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        self.application.add_handler(InlineQueryHandler(self.inline_query))

        
        # Chat member handler for new groups
        self.application.add_handler(ChatMemberHandler(
            self.handle_chat_member_update, 
            ChatMemberHandler.MY_CHAT_MEMBER
        ))
        
        # Track any group where bot sees activity
        self.application.add_handler(MessageHandler(filters.ALL, self.track_groups))
        
        # Clone token input handler (intercepts before forward_user_message_to_admin)
        self.application.add_handler(
            MessageHandler(
                filters.ChatType.PRIVATE & ~filters.COMMAND,
                self.handle_clone_token_input
            ),
            group=0
        )

        # Message forwarding system: User -> Admin
        # Forward all non-command messages from private chats to admin group  
        self.application.add_handler(
            MessageHandler(
                filters.ChatType.PRIVATE & ~filters.COMMAND,
                self.forward_user_message_to_admin
            ),
            group=1
        )
        
        # Message forwarding system: Admin -> User
        # Handle admin replies in admin group and send them to users
        self.application.add_handler(
            MessageHandler(
                filters.Chat(chat_id=ADMIN_GROUP_ID) & filters.REPLY,
                self.handle_admin_reply
            ),
            group=1
        )
 
    async def _set_bot_commands(self):
        """Set bot commands menu"""
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("refresh", "Refresh the bot"),
            BotCommand("language", "Change The Language Of bot"),
            BotCommand("createbuttonpost", "Create a Custom Button Post"),
            BotCommand("mypost", "My All Post"),            
            BotCommand("donate", "Support the bot"),
            BotCommand("developer", "Meet the developer"),
            BotCommand("myscore", "View your achievement report"),
            BotCommand("leaderboard", "Show group leaderboard"),
            BotCommand("sol", "Show Detail Solution"),
            BotCommand("mymistake", "View today's wrong answers"),
        ]
        
        admin_commands = [
            BotCommand("broadcast", "Broadcast message"),
            BotCommand("pbroadcast", "Private broadcast (users only)"),
            BotCommand("stats", "Show bot statistics"),
            BotCommand("promote", "Promote user as admin"),
            BotCommand("remove", "Remove admin"),
            BotCommand("adminlist", "Show admin list"),
            BotCommand("grouplist", "show group list"),
            BotCommand("setsol", "Set Detail Solution"),
            BotCommand("resetleaderboard", "Reset Leaderboard"),
            BotCommand("addpositivereply", "Add positive reply"),
            BotCommand("addnegativereply", "Add negative reply"),
            BotCommand("removereply", "Remove custom reply"),
            BotCommand("forward", "Forward message to all (shows sender)"),
        ]
        
        await self.application.bot.set_my_commands(commands)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        chat = update.effective_chat
        
        # Check force join (only in private chats and groups, not for admins)
        if chat.type != 'channel' and not await db.is_admin(user.id):
            is_joined, missing_groups = await self.check_force_join(user.id, context)
            if not is_joined:
                await self.send_force_join_message(update, context, user.id, missing_groups)
                return
        
        # Add user to database
        await db.add_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        
        # If in group, add user as group member
        if chat.type in ['group', 'supergroup']:
            await db.add_group(chat.id, chat.title, chat.type)
            await db.add_group_member(user.id, chat.id)
        
        # Handle deep link parameters (e.g., /start mymistake)
        if context.args and len(context.args) > 0:
            deep_link_param = context.args[0].lower()
            
            if deep_link_param == 'mymistake':
                # User clicked button from group - show their wrong answers
                try:
                    today = datetime.now(TIMEZONE)
                    wrong_quizzes = await db.get_user_daily_wrong_answers(user.id, today)
                    
                    if not wrong_quizzes:
                        await update.message.reply_text(
                            "🎉 *Congratulations!*\n\n"
                            "✅ Aaj aapne koi galat answer nahi diya!\n"
                            "🏆 Keep up the great work!\n\n"
                            "🤖 @DrQuizRobot",
                            parse_mode='Markdown'
                        )
                        return
                    
                    message = await self.format_wrong_quizzes_message(wrong_quizzes, user.first_name)
                    await update.message.reply_text(message, parse_mode='Markdown')
                    return
                    
                except Exception as e:
                    logger.error(f"Error in start mymistake deep link: {e}")
                    await update.message.reply_text(
                        "❌ Error fetching your wrong answers!\n"
                        "Please try /mymistake command instead.",
                        parse_mode='Markdown'
                    )
                    return
        
        # Create inline keyboard
        keyboard = [
            [InlineKeyboardButton("➕ Add Me in Your Group", url=f"https://t.me/{context.bot.username}?startgroup=true")],
            [InlineKeyboardButton("🧑🏻‍💼 Meet the Owner", url="https://t.me/Aman_PersonalBot")],
            [InlineKeyboardButton("📢 Join Our Community", url="https://t.me/DrQuizRobotUpdates")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = f"""
🎓 **Welcome to NEET Quiz Bot!** 

Hello {user.first_name}! 👋

I'm your dedicated NEET quiz companion, designed to help you ace your medical entrance exams! 🏥📚

**What I can do:**
✅ Forward quizzes from admin group to all connected groups
🏆 Track your performance with points system (+4 correct, -1 wrong)
📊 Daily leaderboards at 10:00 PM IST
💫 Automatic quiz management

**Getting Started:**
1️⃣ Add me to your study groups
2️⃣ Start solving quizzes when they appear
3️⃣ Check daily leaderboards for your progress

Let's ace NEET together! 🚀
        """
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def handle_chat_member_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bot being added to groups"""
        chat = update.effective_chat
        my_member = update.my_chat_member
        
        if my_member.new_chat_member.status in ['member', 'administrator']:
            # Bot was added to group
            await db.add_group(chat.id, chat.title, chat.type)
            logger.info(f"Bot added to group: {chat.title} ({chat.id})")

    async def track_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Automatically register any group or channel where the bot sees activity"""
        chat = update.effective_chat
        if chat and chat.type in ["group", "supergroup", "channel"]:
            # Add to in-memory cache (works even if DB fails)
            self.groups_cache[chat.id] = {
                "title": chat.title or "Unknown Group/Channel",
                "type": chat.type
            }
            # Try to add to database (may fail if DB is down)
            try:
                await db.add_group(chat.id, chat.title or "Unknown Group/Channel", chat.type)
            except Exception as e:
                logger.warning(f"Failed to add group/channel to database: {e}")
    
    async def handle_quiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle quiz messages from admin group"""
        message = update.message
        poll = message.poll
        chat = update.effective_chat
        
        # Only process polls from admin group
        if chat.id != ADMIN_GROUP_ID:
            return
        
        # Accept both quiz and regular poll types, but prefer quiz
        if not poll:
            return
        
        # For regular polls, we'll treat the first option as correct by default
        poll_type = poll.type
        
        try:
            # Validate quiz data
            if not poll.question or not poll.options:
                logger.error("Invalid quiz: missing question or options")
                return
            
            # Handle correct option ID with detailed debugging
            correct_option_id = poll.correct_option_id
            
            # Debug logging to understand what's happening
            logger.info(f"Poll debug info:")
            logger.info(f"  - Poll type: {poll.type}")
            logger.info(f"  - Question: {poll.question[:50]}...")
            logger.info(f"  - Options count: {len(poll.options)}")
            logger.info(f"  - correct_option_id from poll: {correct_option_id}")
            logger.info(f"  - Poll allows_multiple_answers: {poll.allows_multiple_answers}")
            
            # Handle missing correct_option_id (Telegram API limitation) 
            # Do NOT auto-forward quiz without admin setting correct answer
            if correct_option_id is None:
                logger.info(f"⚠️ Quiz received without correct_option_id. Waiting for admin to set correct answer.")
                
                # Store quiz in database with placeholder correct_option (-1 means unset)
                options = [option.text for option in poll.options]
                quiz_id = await db.add_quiz(
                    message_id=message.message_id,
                    from_group_id=chat.id,
                    quiz_text=poll.question,
                    correct_option=-1,  # -1 indicates no correct answer set yet
                    options=options
                )
                
                # Store quiz data for tracking (without correct_option initially)
                self.quiz_data[quiz_id] = {
                    'correct_option': -1,  # Will be updated when admin replies
                    'question': poll.question,
                    'options': options,
                    'message_id': message.message_id,  # Store for reply matching
                    'poll_object': poll  # Store full poll for later forwarding
                }
                
                # Send instruction message to admin
                instruction_text = f"""
📝 **Quiz Received!**

🎯 Question: {poll.question[:100]}{'...' if len(poll.question) > 100 else ''}

⏳ **Please reply to the quiz with correct option:**
• Type: `a`, `b`, `c`, `d` or `1`, `2`, `3`, `4`
• Example: Just reply with `c`

⏰ **Quiz will be forwarded to groups 30 seconds after you set the correct answer.**
                """
                
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=instruction_text,
                    parse_mode='Markdown'
                )
                
                logger.info(f"📋 Quiz {quiz_id} waiting for admin to set correct answer")
                return  # Don't forward yet
            
            if correct_option_id < 0 or correct_option_id >= len(poll.options):
                logger.error(f"Invalid correct_option_id: {correct_option_id} for {len(poll.options)} options")
                return
            
            # This part only runs for quizzes that already have correct_option_id set
            logger.info(f"✅ Quiz has correct_option_id: {correct_option_id}")
            
            # Store quiz in database
            options = [option.text for option in poll.options]
            quiz_id = await db.add_quiz(
                message_id=message.message_id,
                from_group_id=chat.id,
                quiz_text=poll.question,
                correct_option=correct_option_id,
                options=options
            )
        
            # Store quiz data for tracking
            self.quiz_data[quiz_id] = {
                'correct_option': correct_option_id,
                'question': poll.question,
                'options': options,
                'message_id': message.message_id,
                'poll_object': poll
            }
            
            # Schedule delayed forwarding (30 seconds)
            await self._schedule_quiz_forwarding(quiz_id, context)
            
            logger.info(f"⏰ Quiz {quiz_id} scheduled for forwarding in 30 seconds")
            
        except Exception as e:
            logger.error(f"Error handling quiz: {e}")
    
    async def _schedule_quiz_forwarding(self, quiz_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Schedule quiz forwarding after 30 second delay"""
        self.application.job_queue.run_once(
            callback=self._forward_quiz_to_groups,
            when=30,  # 30 seconds delay
            name=f"forward_quiz_{quiz_id}",
            data={'quiz_id': quiz_id}
        )
        logger.info(f"⏰ Quiz {quiz_id} scheduled for forwarding in 30 seconds")
    
    async def _forward_quiz_to_groups(self, context: ContextTypes.DEFAULT_TYPE):
        """Forward quiz to all groups and channels"""
        try:
            # Get quiz_id from job data
            quiz_id = context.job.data['quiz_id']
            
            if quiz_id not in self.quiz_data:
                logger.error(f"Quiz {quiz_id} not found in quiz_data for forwarding")
                return
            
            quiz_data = self.quiz_data[quiz_id]
            correct_option = quiz_data['correct_option']
            
            # Check if correct answer has been set
            if correct_option == -1:
                logger.warning(f"Quiz {quiz_id} still has no correct answer set. Skipping forwarding.")
                # Send reminder to admin
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text="⚠️ Quiz not forwarded - Please set correct answer by replying to the quiz!",
                    parse_mode='Markdown'
                )
                return
            
            # Get all active groups and channels
            all_chats = await db.get_all_groups()
            group_count = 0
            channel_count = 0
            
            poll = quiz_data['poll_object']
            options = quiz_data['options']
            
            for chat in all_chats:
                if chat['id'] != ADMIN_GROUP_ID:  # Don't send back to admin group
                    try:
                        # Get language preference for this chat
                        chat_language = await db.get_group_language(chat['id'])
                        
                        # Determine question and options based on language
                        quiz_question = poll.question
                        quiz_options = options
                        
                        # Translate to Hindi if needed
                        if chat_language == 'hindi':
                            # Check if translation is cached
                            cache_key = (quiz_id, 'hindi')
                            if cache_key in self.translation_cache:
                                # Use cached translation
                                quiz_question = self.translation_cache[cache_key]['question']
                                quiz_options = self.translation_cache[cache_key]['options']
                                logger.info(f"Using cached Hindi translation for quiz {quiz_id}")
                            else:
                                # Translate question and options to Hindi
                                try:
                                    translator = GoogleTranslator(source='auto', target='hi')
                                    
                                    # Translate question
                                    quiz_question = translator.translate(poll.question)
                                    
                                    # Translate options
                                    quiz_options = []
                                    for option in options:
                                        translated_option = translator.translate(option)
                                        quiz_options.append(translated_option)
                                    
                                    # Cache the translation
                                    self.translation_cache[cache_key] = {
                                        'question': quiz_question,
                                        'options': quiz_options
                                    }
                                    logger.info(f"Translated quiz {quiz_id} to Hindi for chat {chat['id']}")
                                    
                                except Exception as translation_error:
                                    # Fallback to English if translation fails
                                    logger.error(f"Translation error for quiz {quiz_id}: {translation_error}")
                                    logger.warning(f"Falling back to English for chat {chat['id']}")
                                    quiz_question = poll.question
                                    quiz_options = options
                        
                        # Add branding mention at the end of question
                        quiz_question = quiz_question + "\n\n【~@DrQuizRobot】"
                        
                        # Send new poll (not forward) with is_anonymous=False
                        sent_message = await context.bot.send_poll(
                            chat_id=chat['id'],
                            question=quiz_question,
                            options=quiz_options,
                            type='quiz',  # Always send as quiz for answer tracking
                            correct_option_id=correct_option,
                            is_anonymous=False,  # Critical: allows us to track user answers
                            explanation=poll.explanation if poll.explanation else "📚 NEET Quiz Bot"
                        )
                        
                        # Store poll mapping for answer tracking
                        self.poll_mapping[sent_message.poll.id] = {
                            'quiz_id': quiz_id,
                            'group_id': chat['id'],
                            'message_id': sent_message.message_id
                        }

                        # Mapping store karo for /sol
                        self.quiz_mapping[sent_message.message_id] = quiz_id

                        # Count groups and channels separately
                        if chat.get('type') == 'channel':
                            channel_count += 1
                            logger.info(f"✅ Quiz sent to channel {chat['id']} with poll_id {sent_message.poll.id}")
                        else:
                            group_count += 1
                            logger.info(f"✅ Quiz sent to group {chat['id']} with poll_id {sent_message.poll.id}")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to send quiz to chat {chat['id']}: {e}")
            
            # Forward to clone bots' groups
            clone_group_count = 0
            clone_channel_count = 0
            for clone_bot_id, instance in clone_manager.get_all_instances().items():
                clone_info = await db.get_clone_bot(clone_bot_id)
                if clone_info and clone_info.get('is_paused'):
                    continue
                clone_groups = await db.get_clone_groups(clone_bot_id)
                for cgroup in clone_groups:
                    try:
                        clone_lang = await db.get_group_language(cgroup['id'])
                        c_question = poll.question
                        c_options = options
                        if clone_lang == 'hindi':
                            cache_key = (quiz_id, 'hindi')
                            if cache_key in self.translation_cache:
                                c_question = self.translation_cache[cache_key]['question']
                                c_options = self.translation_cache[cache_key]['options']
                            else:
                                try:
                                    from deep_translator import GoogleTranslator
                                    translator = GoogleTranslator(source='auto', target='hi')
                                    c_question = translator.translate(poll.question)
                                    c_options = [translator.translate(opt) for opt in options]
                                    self.translation_cache[cache_key] = {'question': c_question, 'options': c_options}
                                except Exception:
                                    c_question = poll.question
                                    c_options = options
                        c_question = c_question + "\n\n【~@" + (instance.bot_username or "QuizBot") + "】"
                        c_sent = await instance.application.bot.send_poll(
                            chat_id=cgroup['id'],
                            question=c_question,
                            options=c_options,
                            type='quiz',
                            correct_option_id=correct_option,
                            is_anonymous=False,
                            explanation=poll.explanation if poll.explanation else "📚 Quiz Bot"
                        )
                        await db.add_poll_mapping(
                            poll_id=c_sent.poll.id,
                            quiz_id=quiz_id,
                            group_id=cgroup['id'],
                            message_id=c_sent.message_id,
                            clone_bot_id=clone_bot_id,
                            correct_option=correct_option
                        )
                        if cgroup.get('type') == 'channel':
                            clone_channel_count += 1
                        else:
                            clone_group_count += 1
                    except Exception as ce:
                        logger.error(f"❌ Clone {clone_bot_id}: Failed to send to {cgroup['id']}: {ce}")

            total_sent = group_count + channel_count
            total_clone = clone_group_count + clone_channel_count
            if total_sent > 0 or total_clone > 0:
                option_letter = chr(65 + correct_option)
                confirmation = (
                    f"🎯 **Quiz Forwarded Successfully!**\n\n"
                    f"📊 Main Bot:\n🏠 Groups: {group_count}\n📢 Channels: {channel_count}\n"
                    f"📊 Clone Bots:\n🏠 Groups: {clone_group_count}\n📢 Channels: {clone_channel_count}\n"
                    f"📈 Total: {total_sent + total_clone}\n\n✅ Correct Answer: **{option_letter}**"
                )
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=confirmation,
                    parse_mode='Markdown'
                )
                logger.info(f"🎯 Quiz forwarded to {group_count}g+{channel_count}c (main) + {clone_group_count}g+{clone_channel_count}c (clones)")
            else:
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text="⚠️ Quiz not sent - No active groups or channels found!",
                    parse_mode='Markdown'
                )
                logger.warning("⚠️ Quiz not sent to any groups or channels")
        
        except Exception as e:
            logger.error(f"Error forwarding quiz {quiz_id}: {e}")
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=f"❌ Error forwarding quiz: {e}",
                parse_mode='Markdown'
            )
    
    async def handle_reply_to_poll(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle replies to poll messages in admin group to capture correct answers"""
        message = update.message
        chat = update.effective_chat
        
        # Only process replies in admin group
        if chat.id != ADMIN_GROUP_ID:
            return
        
        # Check if this is a reply to a poll message
        reply_to_message = message.reply_to_message
        if not reply_to_message or not reply_to_message.poll:
            return
        
        # Parse the reply text for correct option (a, b, c, d)
        reply_text = message.text.lower().strip()
        
        # Map text options to indices
        option_mapping = {
            'a': 0, '1': 0, 'option a': 0, 'a)': 0,
            'b': 1, '2': 1, 'option b': 1, 'b)': 1,
            'c': 2, '3': 2, 'option c': 2, 'c)': 2,
            'd': 3, '4': 3, 'option d': 3, 'd)': 3,
            'e': 4, '5': 4, 'option e': 4, 'e)': 4,
        }
        
        correct_option_index = None
        for text, index in option_mapping.items():
            if text in reply_text:
                correct_option_index = index
                break
        
        if correct_option_index is None:
            # Send help message
            help_text = """
❌ Invalid format! Please reply with correct option:

✅ **Valid formats:**
• `a` or `A` 
• `b` or `B`
• `c` or `C` 
• `d` or `D`
• `1`, `2`, `3`, `4`

**Example:** Reply to quiz with just: `c`
            """
            await message.reply_text(help_text, parse_mode='Markdown')
            return
        
        # Find the quiz in our stored data using message_id
        poll_message_id = reply_to_message.message_id
        quiz_id_to_update = None
        
        # Search through stored quiz data using message_id for better matching
        for quiz_id, quiz_data in self.quiz_data.items():
            # Match by message_id for precise identification
            if quiz_data.get('message_id') == poll_message_id:
                quiz_id_to_update = quiz_id
                break
        
        if quiz_id_to_update is None:
            await message.reply_text("❌ Could not find the quiz to update. Please try again.")
            return
        
        # Validate the option index against available options
        poll_options_count = len(reply_to_message.poll.options)
        if correct_option_index >= poll_options_count:
            await message.reply_text(f"❌ Invalid option! This quiz only has options A-{chr(65 + poll_options_count - 1)}")
            return
        
        # Update the stored quiz data with correct option
        self.quiz_data[quiz_id_to_update]['correct_option'] = correct_option_index
        
        # Also update in database
        await db.update_quiz_correct_option(quiz_id_to_update, correct_option_index)
        
        # Send confirmation
        option_letter = chr(65 + correct_option_index)  # Convert to A, B, C, D
        confirmation_text = f"✅ **Correct Answer Set!**\n\n🎯 Quiz: {reply_to_message.poll.question[:50]}...\n✅ Correct Option: **{option_letter}**\n\n⏰ **Quiz will be forwarded to all groups and channels in 30 seconds!**"
        
        await message.reply_text(confirmation_text, parse_mode='Markdown')
        logger.info(f"🔧 Admin updated quiz {quiz_id_to_update} correct answer to option {correct_option_index} ({option_letter})")
        
        # Schedule forwarding after 30 seconds
        await self._schedule_quiz_forwarding(quiz_id_to_update, context)
    
    async def send_quiz_reply(self, context: ContextTypes.DEFAULT_TYPE, group_id: int, user, reply_type: str):
        """Send quiz reply (text or media) from hardcoded messages + custom replies"""
        try:
            # Get custom replies from database
            custom_replies = await db.get_custom_replies(reply_type)
            
            # Combine hardcoded messages with custom replies for text
            if reply_type == "positive":
                text_replies = CORRECT_MESSAGES.copy()
            else:
                text_replies = WRONG_MESSAGES.copy()
            
            # Add custom text replies to the pool
            custom_text_replies = [r for r in custom_replies if r['message_type'] == 'text']
            for reply in custom_text_replies:
                text_replies.append(reply['content'])
            
            # Get all reply options (text + media)
            all_replies = custom_replies + [{'message_type': 'text', 'content': msg} for msg in (CORRECT_MESSAGES if reply_type == "positive" else WRONG_MESSAGES)]
            
            # Select a random reply
            selected_reply = random.choice(all_replies)
            
            user_mention = f"[{user.first_name}](tg://user?id={user.id})"
            emoji = "🎉" if reply_type == "positive" else "😔"
            
            # Send based on message type
            if selected_reply['message_type'] == 'text':
                await context.bot.send_message(
                    chat_id=group_id,
                    text=f"{emoji} {user_mention} {selected_reply['content']}",
                    parse_mode='Markdown'
                )
            elif selected_reply['message_type'] == 'photo':
                caption = f"{emoji} {user_mention} {selected_reply.get('caption', '')}" if selected_reply.get('caption') else f"{emoji} {user_mention}"
                await context.bot.send_photo(
                    chat_id=group_id,
                    photo=selected_reply['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            elif selected_reply['message_type'] == 'video':
                caption = f"{emoji} {user_mention} {selected_reply.get('caption', '')}" if selected_reply.get('caption') else f"{emoji} {user_mention}"
                await context.bot.send_video(
                    chat_id=group_id,
                    video=selected_reply['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            elif selected_reply['message_type'] == 'document':
                caption = f"{emoji} {user_mention} {selected_reply.get('caption', '')}" if selected_reply.get('caption') else f"{emoji} {user_mention}"
                await context.bot.send_document(
                    chat_id=group_id,
                    document=selected_reply['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            elif selected_reply['message_type'] == 'sticker':
                await context.bot.send_sticker(
                    chat_id=group_id,
                    sticker=selected_reply['file_id']
                )
                await context.bot.send_message(
                    chat_id=group_id,
                    text=f"{emoji} {user_mention}",
                    parse_mode='Markdown'
                )
            elif selected_reply['message_type'] == 'audio':
                caption = f"{emoji} {user_mention} {selected_reply.get('caption', '')}" if selected_reply.get('caption') else f"{emoji} {user_mention}"
                await context.bot.send_audio(
                    chat_id=group_id,
                    audio=selected_reply['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            elif selected_reply['message_type'] == 'voice':
                await context.bot.send_voice(
                    chat_id=group_id,
                    voice=selected_reply['file_id'],
                    caption=f"{emoji} {user_mention}",
                    parse_mode='Markdown'
                )
            elif selected_reply['message_type'] == 'animation':
                caption = f"{emoji} {user_mention} {selected_reply.get('caption', '')}" if selected_reply.get('caption') else f"{emoji} {user_mention}"
                await context.bot.send_animation(
                    chat_id=group_id,
                    animation=selected_reply['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Error sending quiz reply: {e}")
            # Fallback to hardcoded text message
            if reply_type == "positive":
                response = random.choice(CORRECT_MESSAGES)
                await context.bot.send_message(
                    chat_id=group_id,
                    text=f"🎉 [{user.first_name}](tg://user?id={user.id}) {response}",
                    parse_mode='Markdown'
                )
            else:
                response = random.choice(WRONG_MESSAGES)
                await context.bot.send_message(
                    chat_id=group_id,
                    text=f"😔 [{user.first_name}](tg://user?id={user.id}) {response}",
                    parse_mode='Markdown'
                )
    
    async def handle_poll_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle quiz answers"""
        poll_answer = update.poll_answer
        user = poll_answer.user
        poll_id = poll_answer.poll_id
        selected_options = poll_answer.option_ids
        
        # Get poll mapping data
        if poll_id not in self.poll_mapping:
            return
        
        poll_data = self.poll_mapping[poll_id]
        quiz_id = poll_data['quiz_id']
        group_id = poll_data['group_id']
        
        # Get quiz data
        if quiz_id not in self.quiz_data:
            return
        
        quiz_data = self.quiz_data[quiz_id]
        correct_option = quiz_data['correct_option']
        
        # Determine points
        if len(selected_options) == 0:
            points = 0  # Unattempted
            message_type = "unattempted"
        elif selected_options[0] == correct_option:
            points = 4  # Correct
            message_type = "correct"
        else:
            points = -1  # Wrong
            message_type = "wrong"
        
        # Add user to database if not exists
        await db.add_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        
        # Add user to group if not exists
        await db.add_group_member(user.id, group_id)
        
        try:
            # Record the answer with proper group_id
            await db.record_quiz_answer(
                user_id=user.id,
                group_id=group_id,
                quiz_id=quiz_id,
                selected_option=selected_options[0] if selected_options else -1,
                points=points
            )
            
            # Send response message to the GROUP only if replies are enabled
            replies_enabled = await db.is_group_replies_enabled(group_id)
            if replies_enabled:
                if message_type == "correct":
                    await self.send_quiz_reply(context, group_id, user, "positive")
                elif message_type == "wrong":
                    await self.send_quiz_reply(context, group_id, user, "negative")
            
            logger.info(f"Quiz answer recorded: User {user.id}, Group: {group_id}, Points: {points}")
            
        except Exception as e:
            logger.error(f"Error recording quiz answer: {e}")

    # ✅ Admin set karega solution (only in admin group)
    async def set_solution(self, update, context):
        message = update.message
        user_id = message.from_user.id
        chat_id = update.effective_chat.id

        # Admin group check
        if chat_id != ADMIN_GROUP_ID:
            await message.reply_text("❌ /setsol sirf admin group me use kar sakte hain.")
            return

        # Admin check
        is_admin = await db.is_admin(user_id)
        if not is_admin:
            await message.reply_text("❌ Sirf admin hi /setsol use kar sakte hain.")
            return

        # Reply check
        if not message.reply_to_message:
            await message.reply_text("❌ Quiz ke reply me use karo.")
            return

        reply_msg_id = message.reply_to_message.message_id
        
        # Check if it's in quiz_mapping (forwarded quiz) or original quiz in admin group
        quiz_id = None
        if reply_msg_id in self.quiz_mapping:
            quiz_id = self.quiz_mapping[reply_msg_id]
        else:
            # Check if it's an original quiz in admin group
            quiz_data = await db.get_quiz_by_message_id(reply_msg_id, ADMIN_GROUP_ID)
            if quiz_data:
                quiz_id = quiz_data['id']
        
        if not quiz_id:
            await message.reply_text("⚠️ Is message ko quiz ke roop me nahi pehchana gaya.")
            return

        # Solution type detect
        if message.text and len(context.args) > 0:
            sol_type = "text"
            sol_content = " ".join(context.args)
        elif message.photo:
            sol_type = "image"
            sol_content = message.photo[-1].file_id
        elif message.video:
            sol_type = "video"
            sol_content = message.video.file_id
        elif message.document:
            sol_type = "pdf"
            sol_content = message.document.file_id
        else:
            await message.reply_text("❌ Supported formats: text, image, video, pdf, link")
            return

        # DB me insert/update using new method
        await db.set_quiz_solution(quiz_id, sol_type, sol_content)

        await message.reply_text("✅ Solution set ho gaya!")

    # ✅ User solution dekh sakta hai
    async def get_solution(self, update, context):
        message = update.message
        user = update.effective_user
        
        if not await db.is_admin(user.id):
            is_joined, missing_groups = await self.check_force_join(user.id, context)
            if not is_joined:
                await self.send_force_join_message(update, context, user.id, missing_groups)
                return
        
        # If not replying to any message, show usage instructions
        if not message.reply_to_message:
            usage_text = """
📚 **How to use /sol command:**

1️⃣ Find a quiz in any group
2️⃣ Reply to that quiz with `/sol`
3️⃣ Get the detailed solution instantly! 

**Example:**
• Quiz: "What is mitosis?"
• Your reply: `/sol`
• Bot sends: Complete solution with explanation

✨ **Features:**
• Works in any group
• Supports text, images, videos, PDFs
• Get solutions set by admins

🎯 **Note:** Only works when replying to quiz messages!
            """
            await message.reply_text(usage_text, parse_mode='Markdown')
            return

        reply_msg_id = message.reply_to_message.message_id
        if reply_msg_id not in self.quiz_mapping:
            await message.reply_text("⚠️ Is message ko quiz ke roop me nahi pehchana gaya.")
            return

        quiz_id = self.quiz_mapping[reply_msg_id]

        # Get solution using new database method
        solution = await db.get_quiz_solution(quiz_id)

        if not solution:
            # Create redirect button to admin
            keyboard = [
                [InlineKeyboardButton("📞 Contact Admin", url="https://t.me/Aman_PersonalBot")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            no_solution_text = """
❌ **Solution Not Available**

🔍 Is quiz ka solution admin ne abhi set nahi kiya hai.

📞 **Admin se contact karne ke liye neeche button click karo:**
            """
            await message.reply_text(
                no_solution_text, 
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return

        # Send solution based on type
        chat_id = update.effective_chat.id
        if solution["solution_type"] == "text":
            await message.reply_html(f"📘 <b>Solution:</b>\n\n{solution['solution_content']}")
        elif solution["solution_type"] == "image":
            await context.bot.send_photo(chat_id=chat_id, photo=solution["solution_content"], caption="📘 Solution")
        elif solution["solution_type"] == "video":
            await context.bot.send_video(chat_id=chat_id, video=solution["solution_content"], caption="📘 Solution")
        elif solution["solution_type"] == "pdf":
            await context.bot.send_document(chat_id=chat_id, document=solution["solution_content"], caption="📘 Solution")
        elif solution["solution_type"] == "link":
            await message.reply_html(f"🔗 <b>Solution Link:</b> {solution['solution_content']}")
    
    async def refresh_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /refresh command"""
        user = update.effective_user
        
        if not await db.is_admin(user.id):
            is_joined, missing_groups = await self.check_force_join(user.id, context)
            if not is_joined:
                await self.send_force_join_message(update, context, user.id, missing_groups)
                return
        
        await update.message.reply_text("🔄 Bot refreshed successfully! All systems operational. 🚀")
    
    async def donate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /donate command"""
        user = update.effective_user
        
        if not await db.is_admin(user.id):
            is_joined, missing_groups = await self.check_force_join(user.id, context)
            if not is_joined:
                await self.send_force_join_message(update, context, user.id, missing_groups)
                return
        
        # Create donation button
        keyboard = [
            [InlineKeyboardButton("💝 𝗗𝗢𝗡𝗔𝗧𝗘 𝗡𝗢𝗪 💝", url="https://t.me/DrQuizDonationRobot")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        donate_text = f"""
╔═════════════════════════════════════╗
║  💝 𝗦𝗨𝗣𝗣𝗢𝗥𝗧 𝗢𝗨𝗥 𝗠𝗜𝗦𝗦𝗜𝗢𝗡 💝  ║
╚═════════════════════════════════════╝

🌟 Hey {user.first_name}! ✨

🎯 **Your Support Makes Dreams Come True!**

💡 Every donation helps thousands of NEET students:
✅ Access FREE quality quiz questions daily
✅ Improve their preparation with instant scoring  
✅ Compete with peers in real-time leaderboards
✅ Get closer to their MEDICAL COLLEGE dreams! 🏥

🚀 **Why Your Support Matters:**
🔥 Server hosting & maintenance costs
⚡ Adding new features & improvements  
📚 Creating more educational content
🛡️ Ensuring 100% uptime for students

💖 **We've Created Something Special For You:**

🤖 **Secure Donation Bot:** @DrQuizDonationBot
🔒 **100% Safe & Transparent** transactions
🎁 **Special Recognition** for our supporters  
📊 **Impact Reports** - See how you're helping students!

════════════════════════════════════════

🌈 **"Education is the most powerful weapon which you can use to change the world"** - Nelson Mandela

💝 Your kindness today shapes a doctor's journey tomorrow!

🙏 **Thank you for believing in education and our mission!**
        """
        
        await update.message.reply_text(
            donate_text, 
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def developer_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /developer command"""
        user = update.effective_user
        
        if not await db.is_admin(user.id):
            is_joined, missing_groups = await self.check_force_join(user.id, context)
            if not is_joined:
                await self.send_force_join_message(update, context, user.id, missing_groups)
                return
        
        keyboard = [
            [InlineKeyboardButton("💬 Meet With Aman", url="https://t.me/Aman_PersonalBot")],
            [InlineKeyboardButton("🌟 Follow Updates", url="https://t.me/DrQuizRobotUpdates")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        developer_text = f"""
╔═══════════════════════════════════╗
║   🚀 𝗠𝗘𝗘𝗧 𝗧𝗛𝗘 𝗗𝗘𝗩𝗘𝗟𝗢𝗣𝗘𝗥 🚀   ║
╚═══════════════════════════════════╝

👋 Namaste 🇮🇳! ✨

🎯 Meet Aman - The visionary behind this NEET QUIZ BOT

⚡ Who is Aman?
🏢 Founder & CEO of 『Sᴀɴsᴀ Fᴇᴇʟ』
✈️ Owner Of AimAi 【Your Personal Ai Tutor For Neet & Jee Preparation】
🎓 working On Different Projects. 
💻 Tech Innovator building educational solutions
🏆 very soon going to launch Neet Quiz App with multiple features.  

🌟 What Makes Him Special?
✅ Created this FREE quiz bot for students like you
✅ Personally reviews every feature for student benefit  
✅ Available for 1-on-1 chatting, to know the suggestions ideas and feedback 
✅ Passionate about making NEET preparation affordable

═══════════════════════════════════
Let's connect with Aman Directly, privately and securely!
        """
        
        await update.message.reply_text(
            developer_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def myscore_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /Myscore command - show user's achievement report card"""
        user = update.effective_user
        
        # Check force join (not for admins)
        if not await db.is_admin(user.id):
            is_joined, missing_groups = await self.check_force_join(user.id, context)
            if not is_joined:
                await self.send_force_join_message(update, context, user.id, missing_groups)
                return
        
        try:
            # Get user data
            user_data = await db.get_user(user.id)
            if not user_data:
                await update.message.reply_text(
                    "❌ No quiz activity found\\!\n\n"
                    "🎯 Start answering quizzes to see your achievement report\\!",
                    parse_mode='MarkdownV2'
                )
                return
            
            # Get user's universal rank
            universal_rank = await db.get_user_universal_rank(user.id)
            
            # Get user's group-wise scores
            group_scores = await db.get_user_group_scores(user.id)
            
            # Build user profile link - escape markdown characters for MarkdownV2
            user_name = user.first_name
            user_name_escaped = escape_markdown(user_name, version=2)
            user_link = f"[{user_name_escaped}](tg://user?id={user.id})"
            
            # Total score and stats
            total_score = user_data.get('total_score', 0)
            total_correct = user_data.get('correct_answers', 0)
            total_wrong = user_data.get('wrong_answers', 0)
            total_unattempted = user_data.get('unattempted', 0)
            total_quizzes = total_correct + total_wrong + total_unattempted
            
            # Calculate accuracy
            accuracy = (total_correct / total_quizzes * 100) if total_quizzes > 0 else 0
            
            # Get performance badge
            if accuracy >= 90:
                badge = "🏆 MASTER"
            elif accuracy >= 75:
                badge = "💎 EXPERT"
            elif accuracy >= 60:
                badge = "⭐ PRO"
            elif accuracy >= 40:
                badge = "🌟 RISING"
            else:
                badge = "🔰 BEGINNER"
            
            # Current time - escape for MarkdownV2
            current_time = datetime.now(TIMEZONE).strftime('%d %b %Y • %I:%M %p IST')
            current_time_escaped = escape_markdown(current_time, version=2)
            
            # Format and escape accuracy for MarkdownV2
            accuracy_str = f"{accuracy:.1f}%"
            accuracy_escaped = escape_markdown(accuracy_str, version=2)
            
            # Build achievement report card (MarkdownV2 compatible)
            report = f"""
╔══════════════════════════════════╗
║ 🎓 *𝗔𝗖𝗛𝗜𝗘𝗩𝗘𝗠𝗘𝗡𝗧 𝗥𝗘𝗣𝗢𝗥𝗧* 🎓  ║
╚══════════════════════════════════╝

👤 *Student:* {user_link}
📅 *Generated:* {current_time_escaped}
🏅 *Status:* {badge}

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  📊 *𝗨𝗡𝗜𝗩𝗘𝗥𝗦𝗔𝗟 𝗣𝗘𝗥𝗙𝗢𝗥𝗠𝗔𝗡𝗖𝗘*  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

🎯 *Total Score:* `{total_score}` points
🏆 *Universal Rank:* \\#{universal_rank}
📈 *Accuracy:* {accuracy_escaped}

📝 *Quiz Statistics:*
  ✅ Correct: {total_correct}
  ❌ Wrong: {total_wrong}
  ⭕ Unattempted: {total_unattempted}
  📚 Total Quizzes: {total_quizzes}

"""
            
            # Add group-wise performance
            if group_scores:
                report += """┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🏠 *𝗚𝗥𝗢𝗨𝗣 𝗣𝗘𝗥𝗙𝗢𝗥𝗠𝗔𝗡𝗖𝗘*  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

"""
                for i, group in enumerate(group_scores, 1):
                    group_name = group['group_name']
                    # Truncate long group names
                    if len(group_name) > 25:
                        group_name = group_name[:22] + "..."
                    # Escape markdown characters in group name for MarkdownV2
                    group_name = escape_markdown(group_name, version=2)
                    
                    group_score = group['score']
                    group_rank = group['rank']
                    group_correct = group['correct']
                    group_wrong = group['wrong']
                    group_unattempted = group['unattempted']
                    group_total = group_correct + group_wrong + group_unattempted
                    group_accuracy = (group_correct / group_total * 100) if group_total > 0 else 0
                    
                    # Format and escape group accuracy for MarkdownV2
                    group_accuracy_str = f"{group_accuracy:.1f}%"
                    group_accuracy_escaped = escape_markdown(group_accuracy_str, version=2)
                    
                    # Add visual divider for each group
                    if i > 1:
                        report += "─────────────────────────────────\n"
                    
                    report += f"""📍 *{group_name}*
   🎯 Score: `{group_score}` pts \\| Rank: \\#{group_rank}
   📊 Accuracy: {group_accuracy_escaped}
   ✅ {group_correct} \\| ❌ {group_wrong} \\| ⭕ {group_unattempted}

"""
            else:
                report += """┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🏠 *𝗚𝗥𝗢𝗨𝗣 𝗣𝗘𝗥𝗙𝗢𝗥𝗠𝗔𝗡𝗖𝗘*  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📭 No group activity yet\\!
🎯 Join groups and start answering quizzes\\!

"""
            
            # Add branding with founder name
            report += """══════════════════════════════════
🤖 @DrQuizRobot
⚡ Powered By Sansa

👨‍💼 *Founder:* [AMAN](https://t\\.me/Aman\\_PersonalBot)
══════════════════════════════════"""
            
            # Create share button
            # The share button will allow users to forward this message
            # Don't escape for share text as it's URL-encoded, not Markdown
            share_text = f"""🎓 Achievement Report 🎓

👤 {user_name}
🎯 Score: {total_score} pts
🏆 Rank: #{universal_rank}
📈 Accuracy: {accuracy:.1f}%

🤖 @DrQuizRobot
⚡ Powered By Sansa"""
            
            keyboard = [
                [InlineKeyboardButton("📤 Share Your Achievement", 
                                     url=f"https://t.me/share/url?url={quote(share_text)}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send the achievement report
            await update.message.reply_text(
                report,
                reply_markup=reply_markup,
                parse_mode='MarkdownV2'
            )
            
        except Exception as e:
            logger.error(f"Error in myscore command: {e}")
            await update.message.reply_text(
                "❌ Error generating your achievement report\\!\n"
                "Please try again later\\.",
                parse_mode='MarkdownV2'
            )
    
    async def format_wrong_quizzes_message(self, wrong_quizzes: List[Dict], user_name: str) -> str:
        """Format wrong quizzes into a nice message"""
        if not wrong_quizzes:
            return None
        
        today_date = datetime.now(TIMEZONE).strftime('%d %B %Y')
        
        message = f"""
📚 *𝗔𝗔𝗝 𝗞𝗜 𝗚𝗔𝗟𝗧𝗜𝗬𝗔𝗔𝗡* 📚

👤 *{user_name}*
📅 *{today_date}*
❌ *Wrong Answers:* {len(wrong_quizzes)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        for i, quiz in enumerate(wrong_quizzes, 1):
            question = quiz['quiz_text']
            if len(question) > 200:
                question = question[:197] + "..."
            
            # Parse options - handle both list and JSON string formats
            options = quiz['options']
            if isinstance(options, str):
                try:
                    options = json.loads(options)
                except:
                    options = []
            elif not isinstance(options, list):
                options = []
            
            correct_option = quiz['correct_option']
            selected_option = quiz['selected_option']
            
            correct_letter = chr(65 + correct_option) if correct_option >= 0 else "?"
            selected_letter = chr(65 + selected_option) if selected_option >= 0 else "?"
            
            correct_answer = options[correct_option] if 0 <= correct_option < len(options) else "Unknown"
            selected_answer = options[selected_option] if 0 <= selected_option < len(options) else "Unknown"
            
            message += f"""
🔢 *Question {i}:*
{question}

❌ *Tumhara Answer:* {selected_letter}) {selected_answer}
✅ *Sahi Answer:* {correct_letter}) {correct_answer}

─────────────────────────────────
"""
        
        message += """
💡 *Tip:* In questions ko dobara revise karo!
🎯 *Tomorrow try again and score better!*

🤖 @DrQuizRobot
⚡ Powered By Sansa
"""
        return message
    
    async def send_wrong_quizzes_to_user(self, context: ContextTypes.DEFAULT_TYPE, user_id: int, wrong_quizzes: List[Dict], user_name: str):
        """Send wrong quizzes to a user in private chat"""
        try:
            message = await self.format_wrong_quizzes_message(wrong_quizzes, user_name)
            if message:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='Markdown'
                )
                return True
        except Exception as e:
            logger.error(f"Error sending wrong quizzes to user {user_id}: {e}")
        return False
    
    async def mymistake_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /mymistake command - show user's wrong answers for today"""
        user = update.effective_user
        chat = update.effective_chat
        
        # Check force join (not for admins)
        if not await db.is_admin(user.id):
            is_joined, missing_groups = await self.check_force_join(user.id, context)
            if not is_joined:
                await self.send_force_join_message(update, context, user.id, missing_groups)
                return
        
        # If used in a group, send button to redirect to private chat
        if chat.type != 'private':
            bot_username = (await context.bot.get_me()).username
            keyboard = [
                [InlineKeyboardButton(
                    "📩 Check Wrong Answers in Private Chat",
                    url=f"https://t.me/{bot_username}?start=mymistake"
                )]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"👋 *Hey {user.first_name}!*\n\n"
                "📚 Aapki aaj ki wrong answers private chat me milegi!\n"
                "👇 Neeche button click karo:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # In private chat, show wrong quizzes
        try:
            today = datetime.now(TIMEZONE)
            wrong_quizzes = await db.get_user_daily_wrong_answers(user.id, today)
            
            if not wrong_quizzes:
                await update.message.reply_text(
                    "🎉 *Congratulations!*\n\n"
                    "✅ Aaj aapne koi galat answer nahi diya!\n"
                    "🏆 Keep up the great work!\n\n"
                    "🤖 @DrQuizRobot",
                    parse_mode='Markdown'
                )
                return
            
            message = await self.format_wrong_quizzes_message(wrong_quizzes, user.first_name)
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in mymistake command: {e}")
            await update.message.reply_text(
                "❌ Error fetching your wrong answers!\n"
                "Please try again later.",
                parse_mode='Markdown'
            )
    
    async def send_daily_wrong_quiz_summary(self, context: ContextTypes.DEFAULT_TYPE):
        """Scheduled job to send daily wrong quiz summary to all users at 10:10 PM IST"""
        logger.info("🔔 Starting daily wrong quiz summary...")
        
        try:
            today = datetime.now(TIMEZONE)
            
            # Get all users who have wrong answers today
            users_with_wrong = await db.get_users_with_wrong_answers_today(today)
            
            if not users_with_wrong:
                logger.info("No users with wrong answers today")
                return
            
            logger.info(f"Found {len(users_with_wrong)} users with wrong answers today")
            
            success_count = 0
            failed_count = 0
            
            for user_id in users_with_wrong:
                try:
                    # Get user's wrong quizzes
                    wrong_quizzes = await db.get_user_daily_wrong_answers(user_id, today)
                    
                    if not wrong_quizzes:
                        continue
                    
                    # Get user data for name
                    user_data = await db.get_user(user_id)
                    user_name = user_data.get('first_name', 'Student') if user_data else 'Student'
                    
                    # Send wrong quizzes to user
                    success = await self.send_wrong_quizzes_to_user(context, user_id, wrong_quizzes, user_name)
                    
                    if success:
                        success_count += 1
                    else:
                        failed_count += 1
                    
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"Error sending daily summary to user {user_id}: {e}")
                    failed_count += 1
            
            logger.info(f"✅ Daily wrong quiz summary completed: {success_count} sent, {failed_count} failed")
            
        except Exception as e:
            logger.error(f"Error in daily wrong quiz summary: {e}")
    
    async def leaderboard_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /leaderboard command - show current group leaderboard with universal ranks"""
        user = update.effective_user
        chat = update.effective_chat
        
        # Check force join (not for admins)
        if not await db.is_admin(user.id):
            is_joined, missing_groups = await self.check_force_join(user.id, context)
            if not is_joined:
                await self.send_force_join_message(update, context, user.id, missing_groups)
                return
        
        # Only works in groups
        if chat.type == 'private':
            await update.message.reply_text(
                "🏆 **Group Leaderboard**\n\n"
                "❌ This command only works in groups!\n"
                "🔄 Please use this command in a group where the bot is active.",
                parse_mode='Markdown'
            )
            return
        
        try:
            # Get group leaderboard data
            group_leaderboard = await db.get_group_leaderboard(chat.id)
            
            if not group_leaderboard:
                no_data_text = """
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   🏆 *𝗚𝗥𝗢𝗨𝗣 𝗟𝗘𝗔𝗗𝗘𝗥𝗕𝗢𝗔𝗥𝗗* 🏆   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📊 *Current Status:* No quiz activity yet!

🎯 *How to get on the leaderboard:*
  ✅ Answer quiz questions sent by the bot
  ✅ Earn points: +4 ✅ | -1 ❌ | 0 ⭕
  ✅ Compete with group members

🚀 *Start answering quizzes now!*
                """
                await update.message.reply_text(no_data_text, parse_mode='Markdown')
                return
            
            # Build premium decorated leaderboard
            group_title = chat.title or "This Group"
            current_time = datetime.now(TIMEZONE).strftime('%d %b %Y • %I:%M %p IST')
            
            leaderboard_text = f"""
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   🏆 *𝗚𝗥𝗢𝗨𝗣 𝗟𝗘𝗔𝗗𝗘𝗥𝗕𝗢𝗔𝗥𝗗* 🏆   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

🏠 *Group:* {group_title}
📅 *Updated:* {current_time}
👥 *Active Players:* {len(group_leaderboard)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            
            # Add top performers with enhanced decoration
            for i, user in enumerate(group_leaderboard[:20], 1):  # Show top 20
                name = user.get('first_name') or user.get('username') or 'Unknown'
                # Truncate long names
                if len(name) > 20:
                    name = name[:17] + "..."
                    
                score = user['score']
                correct = user['correct']
                wrong = user['wrong'] 
                unattempted = user['unattempted']
                total_attempted = correct + wrong + unattempted
                user_id = user['id']
                
                # Get universal rank
                universal_rank = await db.get_user_universal_rank(user_id)
                
                # Rank emojis and decorations
                if i == 1:
                    rank_display = "🥇 *#1*"
                    decoration = "👑"
                    border = "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
                    border_end = "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
                elif i == 2:
                    rank_display = "🥈 *#2*"
                    decoration = "⭐"
                    border = "┌────────────────────────────┐"
                    border_end = "└────────────────────────────┘"
                elif i == 3:
                    rank_display = "🥉 *#3*"
                    decoration = "✨"
                    border = "┌────────────────────────────┐"
                    border_end = "└────────────────────────────┘"
                else:
                    rank_display = f"🏅 *#{i}*"
                    decoration = "💎" if i <= 5 else "🔥" if i <= 10 else "💪"
                    border = ""
                    border_end = ""
                
                # Performance badge
                if score >= 100:
                    badge = "🚀 *MASTER*"
                elif score >= 50:
                    badge = "⚡ *EXPERT*"
                elif score >= 20:
                    badge = "🎯 *PRO*"
                elif score >= 10:
                    badge = "📈 *RISING*"
                else:
                    badge = "🌱 *BEGINNER*"
                
                # Accuracy calculation
                if total_attempted > 0:
                    accuracy = round((correct / total_attempted) * 100, 1)
                else:
                    accuracy = 0
                
                # Accuracy indicator
                if accuracy >= 90:
                    acc_icon = "💯"
                elif accuracy >= 80:
                    acc_icon = "🎯"
                elif accuracy >= 60:
                    acc_icon = "📊"
                else:
                    acc_icon = "📉"
                
                # Universal rank display
                if universal_rank == 1:
                    univ_display = "🌟 *#1 GLOBAL*"
                elif universal_rank <= 10:
                    univ_display = f"🌟 *#{universal_rank}*"
                elif universal_rank <= 50:
                    univ_display = f"⭐ *#{universal_rank}*"
                elif universal_rank <= 100:
                    univ_display = f"✨ *#{universal_rank}*"
                else:
                    univ_display = f"💫 *#{universal_rank}*"
                
                # Build user entry
                if border:
                    leaderboard_text += f"\n{border}\n"
                
                leaderboard_text += f"""
{rank_display} [{name}](tg://user?id={user_id}) {decoration} {badge}
│ 🌐 *Global:* {univ_display}
│ 💰 *Score:* `{score}` pts  │  📝 *Attempted:* `{total_attempted}`
│ ✅ `{correct}`  │  ❌ `{wrong}`  │  ⭕ `{unattempted}`
│ {acc_icon} *Accuracy:* `{accuracy}%`
"""
                
                if border_end:
                    leaderboard_text += f"{border_end}\n"
                else:
                    leaderboard_text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            
            # Add premium footer
            leaderboard_text += f"""
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🎯 *KEEP PRACTICING TO WIN!* 🎯  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

💡 *Pro Tip:* Consistency is key to success!
🏆 Use /leaderboard anytime to check rankings
            """
            
            await update.message.reply_text(leaderboard_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in leaderboard command: {e}")
            await update.message.reply_text(
                "❌ Sorry, there was an error fetching the leaderboard. Please try again later.",
                parse_mode='Markdown'
            )
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /broadcast command (admin only) - FAST parallel sending"""
        user = update.effective_user
        
        # Check if user is admin
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        # Check if replying to a message
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Please reply to a message to broadcast it.")
            return
        
        replied_message = update.message.reply_to_message
        
        try:
            # Get all groups and users
            groups = await db.get_all_groups()
            users = await db.get_all_users()
            
            # Prepare user list with type info
            user_list = [{'id': u['id'], 'type': 'user'} for u in users]
            all_recipients = groups + user_list
            
            total_count = len(all_recipients)
            
            # Send initial status message
            status_msg = await update.message.reply_text(
                f"📡 Broadcasting to {total_count} recipients...\n\n"
                f"🏠 Groups/Channels: {len(groups)}\n"
                f"👥 Users: {len(users)}\n"
                f"⏳ Please wait (this will be fast!)..."
            )
            
            # Define send function for parallel sending (returns MessageId for tracking)
            async def send_broadcast(chat_id):
                result = await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=replied_message.chat_id,
                    message_id=replied_message.message_id,
                    reply_markup=replied_message.reply_markup
                )
                return result
            
            # Use parallel sender for fast broadcasting with message tracking
            start_time = asyncio.get_event_loop().time()
            success_count, failed_count, results = await self._parallel_send(
                send_broadcast, 
                all_recipients, 
                status_msg, 
                context, 
                "Broadcasting",
                track_messages=True,
                original_message_id=replied_message.message_id,
                original_chat_id=replied_message.chat_id,
                sent_by=user.id
            )
            end_time = asyncio.get_event_loop().time()
            duration = int(end_time - start_time)
            
            # Update status message with results
            await status_msg.edit_text(
                f"✅ Broadcast Complete!\n\n"
                f"📊 Statistics:\n"
                f"🏠 Groups: {results['groups']}\n"
                f"📢 Channels: {results['channels']}\n"
                f"👥 Users: {results['users']}\n"
                f"❌ Failed: {failed_count}\n"
                f"📈 Total Sent: {success_count}/{total_count}\n\n"
                f"⏱️ Time: {duration} seconds"
            )
            
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            await update.message.reply_text("❌ Error occurred during broadcast.")

    async def pbroadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pbroadcast command - Broadcast ONLY to users' private chats (admin only) - FAST parallel"""
        user = update.effective_user
        
        # Check if user is admin
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        # Check if replying to a message
        if not update.message.reply_to_message:
            await update.message.reply_text(
                "❌ Please reply to a message to broadcast it.\n\n"
                "📱 This will send the message ONLY to users' private chats (not groups).\n"
                "Supports: Text, Images, Videos, PDFs, Links, Buttons, Emojis, Stickers, GIFs, and all media types."
            )
            return
        
        replied_message = update.message.reply_to_message
        
        try:
            # Get all users (NOT groups)
            users = await db.get_all_users()
            
            if not users:
                await update.message.reply_text("❌ No users found in database.")
                return
            
            # Prepare user list with type info
            user_list = [{'id': u['id'], 'type': 'user'} for u in users]
            
            # Send initial status message
            status_msg = await update.message.reply_text(
                f"📱 Private Broadcasting to {len(users)} users...\n\n"
                f"⏳ Please wait (this will be fast!)..."
            )
            
            # Define send function for parallel sending
            async def send_private_broadcast(chat_id):
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=replied_message.chat_id,
                    message_id=replied_message.message_id,
                    reply_markup=replied_message.reply_markup
                )
                return True
            
            # Use parallel sender for fast broadcasting
            start_time = asyncio.get_event_loop().time()
            success_count, failed_count, results = await self._parallel_send(
                send_private_broadcast, 
                user_list, 
                status_msg, 
                context, 
                "Private Broadcasting"
            )
            end_time = asyncio.get_event_loop().time()
            duration = int(end_time - start_time)
            
            # Update status message with results
            await status_msg.edit_text(
                f"✅ Private Broadcast Complete!\n\n"
                f"📊 Statistics:\n"
                f"✓ Successful: {success_count}/{len(users)}\n"
                f"✗ Failed: {failed_count}\n"
                f"📱 Sent to: Users' Private Chats Only\n"
                f"🏠 Groups: Not sent (private broadcast)\n\n"
                f"⏱️ Time: {duration} seconds"
            )
            
        except Exception as e:
            logger.error(f"Private broadcast error: {e}")
            await update.message.reply_text("❌ Error occurred during private broadcast.")

    async def forward_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /forward command - Forward message to all groups, channels, and users WITHOUT hiding sender name (admin only) - FAST parallel"""
        user = update.effective_user
        
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        if not update.message.reply_to_message:
            await update.message.reply_text(
                "❌ Please reply to any message to forward it.\n\n"
                "📨 This will FORWARD the message to all groups, channels, and users.\n"
                "👤 Sender's name will be visible (not hidden).\n\n"
                "✅ Supports: Text, Images, Videos, Emojis, Stickers, Polls, Files, Links, and all media types."
            )
            return
        
        replied_message = update.message.reply_to_message
        
        try:
            groups = await db.get_all_groups()
            users = await db.get_all_users()
            
            # Prepare user list with type info
            user_list = [{'id': u['id'], 'type': 'user'} for u in users]
            all_recipients = groups + user_list
            
            total_count = len(all_recipients)
            
            status_msg = await update.message.reply_text(
                f"📨 Forwarding to {total_count} recipients...\n\n"
                f"🏠 Groups/Channels: {len(groups)}\n"
                f"👥 Users: {len(users)}\n"
                f"⏳ Please wait (this will be fast!)..."
            )
            
            # Define send function for parallel sending
            async def send_forward(chat_id):
                await context.bot.forward_message(
                    chat_id=chat_id,
                    from_chat_id=replied_message.chat_id,
                    message_id=replied_message.message_id
                )
                return True
            
            # Use parallel sender for fast forwarding
            start_time = asyncio.get_event_loop().time()
            success_count, failed_count, results = await self._parallel_send(
                send_forward, 
                all_recipients, 
                status_msg, 
                context, 
                "Forwarding"
            )
            end_time = asyncio.get_event_loop().time()
            duration = int(end_time - start_time)
            
            await status_msg.edit_text(
                f"✅ Forward Complete!\n\n"
                f"📊 Statistics:\n"
                f"🏠 Groups: {results['groups']}\n"
                f"📢 Channels: {results['channels']}\n"
                f"👥 Users: {results['users']}\n"
                f"❌ Failed: {failed_count}\n"
                f"📈 Total Sent: {success_count}/{total_count}\n\n"
                f"👤 Sender name: Visible\n"
                f"⏱️ Time: {duration} seconds"
            )
            
        except Exception as e:
            logger.error(f"Forward error: {e}")
            await update.message.reply_text("❌ Error occurred during forwarding.")

    async def emergency_broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /emergencybroadcast or /ebroadcast command - works WITHOUT database - FAST parallel"""
        user = update.effective_user
    
        # Hardcoded admin check (works even if DB is down)
        EMERGENCY_ADMINS = [8147394357, 8162524828]  # ⬅️ APNE ADMIN IDs YAHAN DALO
        if user.id not in EMERGENCY_ADMINS:
            await update.message.reply_text("❌ You are not authorized to use this emergency command.")
            return
    
        # Check if replying to a message
        if not update.message.reply_to_message:
            await update.message.reply_text(
                "❌ Please reply to a message/media/poll/quiz to broadcast it.\n\n"
                "⚠️ **Emergency Mode**: Using in-memory cache (works without database)"
            )
            return
    
        replied_message = update.message.reply_to_message
    
        try:
            # Use in-memory cache instead of database
            if not self.groups_cache:
                await update.message.reply_text(
                    "⚠️ **No groups in cache!**\n\n"
                    "The bot needs to receive at least one message from each group to build the cache.\n"
                    "If database is working, use /broadcast instead."
                )
                return
        
            # Prepare cache list for parallel sending
            cache_list = [{'id': gid, 'type': info.get('type', 'group')} for gid, info in self.groups_cache.items()]
        
            status_msg = await update.message.reply_text(
                f"🔄 **Emergency Broadcast Started**\n\n"
                f"📊 Groups in cache: {len(self.groups_cache)}\n"
                f"⏳ Sending messages (fast mode)..."
            )
            
            # Define send function for parallel sending
            async def send_emergency(chat_id):
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=replied_message.chat_id,
                    message_id=replied_message.message_id
                )
                return True
            
            # Use parallel sender for fast broadcasting
            start_time = asyncio.get_event_loop().time()
            success_count, failed_count, results = await self._parallel_send(
                send_emergency, 
                cache_list, 
                status_msg, 
                context, 
                "Emergency Broadcasting"
            )
            end_time = asyncio.get_event_loop().time()
            duration = int(end_time - start_time)
        
            # Update status
            await status_msg.edit_text(
                f"✅ **Emergency Broadcast Complete!**\n\n"
                f"📊 **Statistics:**\n"
                f"   🏠 Groups: {results['groups']}\n"
                f"   📢 Channels: {results['channels']}\n"
                f"   ✅ Successful: {success_count}\n"
                f"   ❌ Failed: {failed_count}\n"
                f"   📝 Total in cache: {len(self.groups_cache)}\n\n"
                f"⏱️ Time: {duration} seconds\n"
                f"⚠️ **Note:** Used in-memory cache (no database required)"
            )
        
        except Exception as e:
            logger.error(f"Emergency broadcast error: {e}")
            await update.message.reply_text(
                f"❌ **Emergency broadcast failed!**\n\n"
                f"Error: {str(e)}"
            )
    
    async def gbroadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /gbroadcast command - Broadcast ONLY to groups and channels (admin only) - FAST parallel"""
        user = update.effective_user
        
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        if not update.message.reply_to_message:
            await update.message.reply_text(
                "❌ Please reply to a message to broadcast it.\n\n"
                "🏢 This will send the message ONLY to groups and channels (not private chats).\n"
                "Supports: Text, Images, Videos, PDFs, Polls, Buttons, Emojis, Stickers, GIFs, and all media types."
            )
            return
        
        replied_message = update.message.reply_to_message
        
        try:
            groups = await db.get_all_groups()
            
            if not groups:
                await update.message.reply_text("❌ No groups found in database.")
                return
            
            status_msg = await update.message.reply_text(
                f"🏢 Group Broadcasting to {len(groups)} groups/channels...\n\n"
                f"⏳ Please wait (this will be fast!)..."
            )
            
            # Define send function for parallel sending
            async def send_group_broadcast(chat_id):
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=replied_message.chat_id,
                    message_id=replied_message.message_id,
                    reply_markup=replied_message.reply_markup
                )
                return True
            
            # Use parallel sender for fast broadcasting
            start_time = asyncio.get_event_loop().time()
            success_count, failed_count, results = await self._parallel_send(
                send_group_broadcast, 
                groups, 
                status_msg, 
                context, 
                "Group Broadcasting"
            )
            end_time = asyncio.get_event_loop().time()
            duration = int(end_time - start_time)
            
            await status_msg.edit_text(
                f"✅ Group Broadcast Complete!\n\n"
                f"📊 Statistics:\n"
                f"🏠 Groups: {results['groups']}\n"
                f"📢 Channels: {results['channels']}\n"
                f"❌ Failed: {failed_count}\n"
                f"📈 Total Sent: {success_count}/{len(groups)}\n\n"
                f"👤 Private Chats: Not sent (group broadcast)\n"
                f"⏱️ Time: {duration} seconds"
            )
            
        except Exception as e:
            logger.error(f"Group broadcast error: {e}")
            await update.message.reply_text("❌ Error occurred during group broadcast.")
    
    async def promotion_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /promotion command - Show promotional message (available to all users)"""
        
        keyboard = [[InlineKeyboardButton("📢 Contact for Promotion", url="https://t.me/sansaadsbot")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        promotion_text = """
╔═══════════════════════════════════╗
║   🚀 **PROMOTE YOUR BUSINESS!** 🚀   ║
╚═══════════════════════════════════╝

📣 **Get Maximum Reach & Visibility!**

✨ **We Promote:**
   • 📱 Telegram Groups & Channels
   • 🤖 Bots & Applications
   • 🏢 Brands & Startups
   • 📦 Products & Services
   • 💼 Business Ventures

💎 **Why Choose Us?**
   ✓ Best Market Prices
   ✓ Targeted Audience Reach
   ✓ Professional Service
   ✓ Quick Delivery
   ✓ Proven Results

💰 **Affordable Packages Available!**

┌─────────────────────────────────┐
│  📞 **CONTACT US NOW:**           │
│  Click the button below! ↓        │
└─────────────────────────────────┘

⚡ *Limited Time Offers!*
🎯 *Grow Your Presence Today!*
        """
        
        await update.message.reply_text(
            promotion_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command (admin only)"""
        user = update.effective_user
        
        # Check if user is admin
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        try:
            stats = await db.get_bot_stats()
            
            stats_text = f"""
📊 **Bot Statistics**

👥 **Total Users:** {stats['total_users']}
🏢 **Total Groups:** {stats['total_groups']}
❓ **Total Quizzes:** {stats['total_quizzes']}
✏️ **Total Answers:** {stats['total_answers']}

🕒 **Last Updated:** {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S IST')}
            """
            
            await update.message.reply_text(stats_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Stats error: {e}")
            await update.message.reply_text("❌ Error fetching statistics.")
    
    async def promote_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /promote command (admin only)"""
        user = update.effective_user
        
        # Check if user is admin
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        # Parse user ID from command
        try:
            user_id = int(context.args[0])
        except (IndexError, ValueError):
            await update.message.reply_text("❌ Please provide a valid user ID.\nUsage: /promote <user_id>")
            return
        
        try:
            await db.add_admin(user_id=user_id, promoted_by=user.id)
            await update.message.reply_text(f"✅ User {user_id} has been promoted to admin.")
            
        except Exception as e:
            logger.error(f"Promote error: {e}")
            await update.message.reply_text("❌ Error promoting user.")
    
    async def remove_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove command (admin only)"""
        user = update.effective_user
        
        # Check if user is admin
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        # Parse user ID from command
        try:
            user_id = int(context.args[0])
        except (IndexError, ValueError):
            await update.message.reply_text("❌ Please provide a valid user ID.\nUsage: /remove <user_id>")
            return
        
        try:
            await db.remove_admin(user_id)
            await update.message.reply_text(f"✅ User {user_id} has been removed from admin list.")
            
        except Exception as e:
            logger.error(f"Remove admin error: {e}")
            await update.message.reply_text("❌ Error removing admin.")

    async def adminlist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /adminlist command (admin only)"""
        user = update.effective_user
        
        # Check if user is admin
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        try:
            admins = await db.get_all_admins()
            
            if not admins:
                await update.message.reply_text("👥 No admins found.")
                return
            
            admin_text = "👑 **Current Bot Admins:**\n\n"
            for admin in admins:
                admin_text += f"• **{admin['first_name'] or 'Unknown'}** (@{admin['username'] or 'N/A'})\n"
                admin_text += f"  ID: `{admin['user_id']}`\n"
                admin_text += f"  Since: {admin['created_at'].strftime('%Y-%m-%d')}\n\n"
            
            await update.message.reply_text(admin_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Admin list error: {e}")
            await update.message.reply_text("❌ Error fetching admin list.")

    async def reset_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reset universal + group leaderboard (admin only)"""
        user_id = update.effective_user.id

        # Admin check
        is_admin = await db.fetchval("SELECT 1 FROM admins WHERE user_id=$1", user_id)
        if not is_admin:
            await update.message.reply_text("❌ Sirf admin hi /resetleaderboard use kar sakte hain.")
            return

        # Reset leaderboard
        await db.execute("""
            UPDATE users
            SET total_score=0,
                correct_answers=0,
                wrong_answers=0,
                unattempted=0,
                updated_at=NOW()
        """)
        await db.execute("TRUNCATE TABLE user_quiz_scores RESTART IDENTITY CASCADE")

        await update.message.reply_text("✅ Leaderboard reset ho gaya. Ab points fir se count honge.")
        logger.info(f"Leaderboard reset by admin {user_id}")
    
    async def grouplist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /grouplist command (admin only)"""
        user = update.effective_user
        
        # ✅ Sirf admin ke liye
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return

        try:
            groups = await db.get_all_groups()
            if not groups:
                await update.message.reply_text("🤷‍♂️ Bot is not in any groups yet.")
                return

            # Group list banani hai
            text = "📋 **Groups where bot is active:**\n\n"
            for i, group in enumerate(groups, start=1):
                try:
                    chat = await context.bot.get_chat(group['id'])  # Group ka naam
                    members_count = await context.bot.get_chat_member_count(group['id'])  # Members count
                    group_link = f"https://t.me/c/{str(group['id'])[4:]}" if str(group['id']).startswith("-100") else None

                    if group_link:
                        text += f"{i}. [{chat.title}]({group_link}) (@{chat.username}) — 👥 {members_count} members\n"
                    else:
                        text += f"{i}. {chat.title} (@{chat.username}) — 👥 {members_count} members\n"
            
                except Exception as e:
                    text += f"{i}. ❌ Failed to fetch group info (ID: {group['id']})\n"
                    continue

            await update.message.reply_text(text, parse_mode="Markdown")

        except Exception as e:
            await update.message.reply_text("❌ Error fetching group list.")
            logger.error(f"Grouplist error: {e}")
    
    async def add_positive_reply_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addpositivereply command (admin only)"""
        user = update.effective_user
        
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Please reply to a message/media to add it as a positive reply.")
            return
        
        replied_msg = update.message.reply_to_message
        
        try:
            message_type = None
            content = None
            file_id = None
            caption = None
            
            if replied_msg.text:
                message_type = "text"
                content = replied_msg.text
            elif replied_msg.photo:
                message_type = "photo"
                file_id = replied_msg.photo[-1].file_id
                caption = replied_msg.caption
            elif replied_msg.video:
                message_type = "video"
                file_id = replied_msg.video.file_id
                caption = replied_msg.caption
            elif replied_msg.document:
                message_type = "document"
                file_id = replied_msg.document.file_id
                caption = replied_msg.caption
            elif replied_msg.sticker:
                message_type = "sticker"
                file_id = replied_msg.sticker.file_id
            elif replied_msg.audio:
                message_type = "audio"
                file_id = replied_msg.audio.file_id
                caption = replied_msg.caption
            elif replied_msg.voice:
                message_type = "voice"
                file_id = replied_msg.voice.file_id
                caption = replied_msg.caption
            elif replied_msg.animation:
                message_type = "animation"
                file_id = replied_msg.animation.file_id
                caption = replied_msg.caption
            else:
                await update.message.reply_text("❌ Unsupported message type.")
                return
            
            reply_id = await db.add_custom_reply(
                reply_type="positive",
                message_type=message_type,
                content=content,
                file_id=file_id,
                caption=caption,
                added_by=user.id
            )
            
            await update.message.reply_text(f"✅ Positive reply added successfully! (ID: {reply_id})")
            logger.info(f"Admin {user.id} added positive reply: {message_type}")
            
        except Exception as e:
            logger.error(f"Error adding positive reply: {e}")
            await update.message.reply_text("❌ Error adding positive reply.")
    
    async def add_negative_reply_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addnegativereply command (admin only)"""
        user = update.effective_user
        
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Please reply to a message/media to add it as a negative reply.")
            return
        
        replied_msg = update.message.reply_to_message
        
        try:
            message_type = None
            content = None
            file_id = None
            caption = None
            
            if replied_msg.text:
                message_type = "text"
                content = replied_msg.text
            elif replied_msg.photo:
                message_type = "photo"
                file_id = replied_msg.photo[-1].file_id
                caption = replied_msg.caption
            elif replied_msg.video:
                message_type = "video"
                file_id = replied_msg.video.file_id
                caption = replied_msg.caption
            elif replied_msg.document:
                message_type = "document"
                file_id = replied_msg.document.file_id
                caption = replied_msg.caption
            elif replied_msg.sticker:
                message_type = "sticker"
                file_id = replied_msg.sticker.file_id
            elif replied_msg.audio:
                message_type = "audio"
                file_id = replied_msg.audio.file_id
                caption = replied_msg.caption
            elif replied_msg.voice:
                message_type = "voice"
                file_id = replied_msg.voice.file_id
                caption = replied_msg.caption
            elif replied_msg.animation:
                message_type = "animation"
                file_id = replied_msg.animation.file_id
                caption = replied_msg.caption
            else:
                await update.message.reply_text("❌ Unsupported message type.")
                return
            
            reply_id = await db.add_custom_reply(
                reply_type="negative",
                message_type=message_type,
                content=content,
                file_id=file_id,
                caption=caption,
                added_by=user.id
            )
            
            await update.message.reply_text(f"✅ Negative reply added successfully! (ID: {reply_id})")
            logger.info(f"Admin {user.id} added negative reply: {message_type}")
            
        except Exception as e:
            logger.error(f"Error adding negative reply: {e}")
            await update.message.reply_text("❌ Error adding negative reply.")
    
    async def remove_reply_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /removereply command (admin only)"""
        user = update.effective_user
        
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Please reply to a message/media to remove it from custom replies.")
            return
        
        replied_msg = update.message.reply_to_message
        
        try:
            content = None
            file_id = None
            
            if replied_msg.text:
                content = replied_msg.text
            elif replied_msg.photo:
                file_id = replied_msg.photo[-1].file_id
            elif replied_msg.video:
                file_id = replied_msg.video.file_id
            elif replied_msg.document:
                file_id = replied_msg.document.file_id
            elif replied_msg.sticker:
                file_id = replied_msg.sticker.file_id
            elif replied_msg.audio:
                file_id = replied_msg.audio.file_id
            elif replied_msg.voice:
                file_id = replied_msg.voice.file_id
            elif replied_msg.animation:
                file_id = replied_msg.animation.file_id
            else:
                await update.message.reply_text("❌ Unsupported message type.")
                return
            
            deleted_count = await db.remove_custom_reply(content=content, file_id=file_id)
            
            if deleted_count > 0:
                await update.message.reply_text(f"✅ Custom reply removed successfully! ({deleted_count} entries deleted)")
                logger.info(f"Admin {user.id} removed {deleted_count} custom reply(ies)")
            else:
                await update.message.reply_text("❌ No matching custom reply found in database.")
            
        except Exception as e:
            logger.error(f"Error removing custom reply: {e}")
            await update.message.reply_text("❌ Error removing custom reply.")
    
    async def replyoff_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /replyoff command - disable replies in group (admin/group admin only)"""
        user = update.effective_user
        chat = update.effective_chat
        
        # Only works in groups
        if chat.type not in ['group', 'supergroup']:
            await update.message.reply_text("❌ This command can only be used in groups.")
            return
        
        # Check if user is bot admin or group admin
        is_bot_admin = await db.is_admin(user.id)
        
        # Check if user is group admin
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            is_group_admin = member.status in ['creator', 'administrator']
        except:
            is_group_admin = False
        
        # If neither bot admin nor group admin, deny access
        if not is_bot_admin and not is_group_admin:
            await update.message.reply_text(
                "🚫 **𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗**\n\n"
                "❌ 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙞𝙨 𝙤𝙣𝙡𝙮 𝙛𝙤𝙧 𝙖𝙙𝙢𝙞𝙣𝙨!\n\n"
                "👮‍♂️ Only group admins and bot admins can use this command.",
                parse_mode='Markdown'
            )
            return
        
        # Disable replies for this group
        await db.set_group_replies_status(chat.id, False)
        
        await update.message.reply_text(
            "🔕 **𝗥𝗘𝗣𝗟𝗜𝗘𝗦 𝗗𝗜𝗦𝗔𝗕𝗟𝗘𝗗**\n\n"
            "✅ Quiz replies have been turned OFF for this group.\n\n"
            "📌 Users can still answer quizzes and earn points.\n"
            "💬 But bot won't send congratulatory/failure messages.\n\n"
            "🔔 Use /replyon to enable replies again.",
            parse_mode='Markdown'
        )
        logger.info(f"User {user.id} disabled replies in group {chat.id}")
    
    async def replyon_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /replyon command - enable replies in group (admin/group admin only)"""
        user = update.effective_user
        chat = update.effective_chat
        
        # Only works in groups
        if chat.type not in ['group', 'supergroup']:
            await update.message.reply_text("❌ This command can only be used in groups.")
            return
        
        # Check if user is bot admin or group admin
        is_bot_admin = await db.is_admin(user.id)
        
        # Check if user is group admin
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            is_group_admin = member.status in ['creator', 'administrator']
        except:
            is_group_admin = False
        
        # If neither bot admin nor group admin, deny access
        if not is_bot_admin and not is_group_admin:
            await update.message.reply_text(
                "🚫 **𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗**\n\n"
                "❌ 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙞𝙨 𝙤𝙣𝙡𝙮 𝙛𝙤𝙧 𝙖𝙙𝙢𝙞𝙣𝙨!\n\n"
                "👮‍♂️ Only group admins and bot admins can use this command.",
                parse_mode='Markdown'
            )
            return
        
        # Enable replies for this group
        await db.set_group_replies_status(chat.id, True)
        
        await update.message.reply_text(
            "🔔 **𝗥𝗘𝗣𝗟𝗜𝗘𝗦 𝗘𝗡𝗔𝗕𝗟𝗘𝗗**\n\n"
            "✅ Quiz replies have been turned ON for this group.\n\n"
            "🎉 Bot will now send congratulatory messages for correct answers.\n"
            "😔 And failure messages for wrong answers.\n\n"
            "🔕 Use /replyoff to disable replies.",
            parse_mode='Markdown'
        )
        logger.info(f"User {user.id} enabled replies in group {chat.id}")
    
    async def language_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /language command - set quiz language preference"""
        user = update.effective_user
        chat = update.effective_chat
        
        # Check force join for private chats (not for admins)
        if chat.type == 'private' and not await db.is_admin(user.id):
            is_joined, missing_groups = await self.check_force_join(user.id, context)
            if not is_joined:
                await self.send_force_join_message(update, context, user.id, missing_groups)
                return
        
        # In groups: Check if user is bot admin or group admin
        if chat.type in ['group', 'supergroup']:
            # Check if user is bot admin
            is_bot_admin = await db.is_admin(user.id)
            
            # Check if user is group admin
            try:
                member = await context.bot.get_chat_member(chat.id, user.id)
                is_group_admin = member.status in ['creator', 'administrator']
            except:
                is_group_admin = False
            
            # If neither bot admin nor group admin, deny access
            if not is_bot_admin and not is_group_admin:
                await update.message.reply_text(
                    "🚫 **𝗔𝗖𝗖𝗘𝗦𝗦 𝗗𝗘𝗡𝗜𝗘𝗗**\n\n"
                    "❌ 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙞𝙨 𝙤𝙣𝙡𝙮 𝙛𝙤𝙧 𝙖𝙙𝙢𝙞𝙣𝙨 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥𝙨!\n\n"
                    "👮‍♂️ Only group admins and bot admins can change language in groups.",
                    parse_mode='Markdown'
                )
                return
        
        # Create inline keyboard with language options
        keyboard = [
            [
                InlineKeyboardButton("🇬🇧 English", callback_data=f"lang_english_{chat.id}"),
                InlineKeyboardButton("🇮🇳 हिंदी", callback_data=f"lang_hindi_{chat.id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get current language preference
        if chat.type in ['group', 'supergroup']:
            current_lang = await db.get_group_language(chat.id)
        else:
            current_lang = await db.get_user_language(user.id)
        lang_display = "English" if current_lang == 'english' else "हिंदी (Hindi)"
        
        await update.message.reply_text(
            f"🌐 **𝗟𝗔𝗡𝗚𝗨𝗔𝗚𝗘 𝗦𝗘𝗟𝗘𝗖𝗧𝗜𝗢𝗡**\n\n"
            f"📌 Current Language: **{lang_display}**\n\n"
            f"🔤 Choose quiz language:\n"
            f"• English: Quizzes in English\n"
            f"• हिंदी: प्रश्न हिंदी में\n\n"
            f"📊 Note: All users share same leaderboard regardless of language!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        logger.info(f"User {user.id} opened language selection in chat {chat.id}")
    
    async def fjoin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /fjoin command to add force join groups (admin only)"""
        user = update.effective_user
        
        # Check if user is admin
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        # Check if argument is provided
        if not context.args or len(context.args) == 0:
            await update.message.reply_text(
                "📝 **Usage:**\n`/fjoin @username` or `/fjoin group_link`\n\n"
                "**Examples:**\n"
                "`/fjoin @neetquizgroup`\n"
                "`/fjoin https://t.me/neetquizgroup`",
                parse_mode='Markdown'
            )
            return
        
        group_identifier = context.args[0]
        
        try:
            # Try to get chat info
            if group_identifier.startswith('@'):
                chat = await context.bot.get_chat(group_identifier)
            elif group_identifier.startswith('https://t.me/'):
                username = group_identifier.split('/')[-1]
                chat = await context.bot.get_chat(f'@{username}')
            elif group_identifier.lstrip('-').isdigit():
                chat = await context.bot.get_chat(int(group_identifier))
            else:
                await update.message.reply_text("❌ Invalid format. Use @username or https://t.me/username")
                return
            
            # Check if limit reached
            current_count = await db.get_force_join_count()
            if current_count >= 5:
                await update.message.reply_text(
                    "⚠️ **Limit Reached!**\n\n"
                    "Maximum 5 groups/channels can be added to force join.\n"
                    "Remove one using `/removefjoin` first.",
                    parse_mode='Markdown'
                )
                return
            
            # Get invite link if available
            invite_link = None
            try:
                if chat.username:
                    invite_link = f"https://t.me/{chat.username}"
                else:
                    # Try to get invite link
                    invite = await context.bot.export_chat_invite_link(chat.id)
                    invite_link = invite
            except:
                pass
            
            # Add to force join
            success = await db.add_force_join_group(
                chat_id=chat.id,
                chat_username=chat.username,
                chat_title=chat.title,
                chat_type=chat.type,
                invite_link=invite_link,
                added_by=user.id
            )
            
            if success:
                await update.message.reply_text(
                    f"✅ **Force Join Added!**\n\n"
                    f"📢 **Group:** {chat.title or chat.username}\n"
                    f"🆔 **ID:** `{chat.id}`\n"
                    f"🔗 **Link:** {invite_link or 'Not available'}\n\n"
                    f"📊 **Total Force Join Groups:** {current_count + 1}/5",
                    parse_mode='Markdown'
                )
                logger.info(f"Admin {user.id} added force join group {chat.id}")
            else:
                await update.message.reply_text("❌ Failed to add group to force join list.")
                
        except Exception as e:
            logger.error(f"Error in fjoin command: {e}")
            await update.message.reply_text(
                f"❌ Error: {str(e)}\n\n"
                "Make sure the bot is admin in the group/channel.",
                parse_mode='Markdown'
            )
    
    async def removefjoin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /removefjoin command to remove force join groups (admin only)"""
        user = update.effective_user
        
        # Check if user is admin
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        
        # Check if argument is provided
        if not context.args or len(context.args) == 0:
            # Show current force join list
            force_join_groups = await db.get_force_join_groups()
            if not force_join_groups:
                await update.message.reply_text("📭 No force join groups configured.")
                return
            
            message = "📋 **Current Force Join Groups:**\n\n"
            for idx, group in enumerate(force_join_groups, 1):
                message += f"{idx}. **{group['chat_title'] or group['chat_username']}**\n"
                message += f"   🆔 ID: `{group['chat_id']}`\n"
                message += f"   🔗 {group['invite_link'] or 'No link'}\n\n"
            
            message += "\n📝 **Usage:** `/removefjoin chat_id`\n"
            message += "**Example:** `/removefjoin -1001234567890`"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            return
        
        chat_id_str = context.args[0]
        
        try:
            # Convert to integer
            if chat_id_str.lstrip('-').isdigit():
                chat_id = int(chat_id_str)
            else:
                await update.message.reply_text("❌ Invalid chat ID. Use numeric ID like `-1001234567890`")
                return
            
            # Remove from force join
            success = await db.remove_force_join_group(chat_id)
            
            if success:
                await update.message.reply_text(
                    f"✅ **Force Join Removed!**\n\n"
                    f"🆔 **Chat ID:** `{chat_id}`\n"
                    f"📊 **Remaining:** {await db.get_force_join_count()}/5",
                    parse_mode='Markdown'
                )
                logger.info(f"Admin {user.id} removed force join group {chat_id}")
            else:
                await update.message.reply_text("❌ Group not found in force join list.")
                
        except Exception as e:
            logger.error(f"Error in removefjoin command: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode='Markdown')
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        # Check force join ONLY for private chat callbacks (not for groups, not for admins)
        if query.message and query.message.chat.type == 'private':
            if not await db.is_admin(user.id):
                is_joined, missing_groups = await self.check_force_join(user.id, context)
                if not is_joined:
                    await query.answer("❌ Please join all required groups first!", show_alert=True)
                    await self.send_force_join_message(update, context, user.id, missing_groups)
                    return
        
        # Handle language selection callbacks
        if query.data.startswith("lang_"):
            parts = query.data.split("_")
            if len(parts) == 3:
                language = parts[1]  # english or hindi
                chat_id = int(parts[2])
                
                # Verify user has permission (for groups)
                chat = await context.bot.get_chat(chat_id)
                if chat.type in ['group', 'supergroup']:
                    user = query.from_user
                    is_bot_admin = await db.is_admin(user.id)
                    
                    try:
                        member = await context.bot.get_chat_member(chat_id, user.id)
                        is_group_admin = member.status in ['creator', 'administrator']
                    except:
                        is_group_admin = False
                    
                    if not is_bot_admin and not is_group_admin:
                        await query.answer("❌ Only admins can change language!", show_alert=True)
                        return
                
                # Set language preference (use user table for private chats)
                if chat.type == 'private':
                    await db.set_user_language(chat_id, language)
                else:
                    await db.set_group_language(chat_id, language)
                    # Update groups cache with language
                    if chat_id in self.groups_cache:
                        self.groups_cache[chat_id]['language'] = language
                
                lang_display = "English 🇬🇧" if language == 'english' else "हिंदी 🇮🇳"
                
                await query.edit_message_text(
                    f"✅ **𝗟𝗔𝗡𝗚𝗨𝗔𝗚𝗘 𝗨𝗣𝗗𝗔𝗧𝗘𝗗**\n\n"
                    f"🌐 Quiz Language: **{lang_display}**\n\n"
                    f"{'📝 Quizzes will now appear in English' if language == 'english' else '📝 अब प्रश्न हिंदी में आएंगे'}\n\n"
                    f"📊 Leaderboard remains same for all languages!",
                    parse_mode='Markdown'
                )
                logger.info(f"Language set to {language} for chat {chat_id}")
        else:
            # Handle any other callback queries if needed
            logger.info(f"Callback query: {query.data}")
    
    async def send_daily_leaderboards(self, context: ContextTypes.DEFAULT_TYPE = None):
        """Send daily leaderboards at 10:00 PM IST to groups and users' private chats - shows last 24 hours scores"""
        try:
            groups = await db.get_all_groups()
            all_users = await db.get_all_users()
            
            # Precompute daily universal ranks (last 24 hours) for efficiency
            daily_universal_leaderboard = await db.get_daily_universal_leaderboard(1000)  # Get top 1000
            daily_rank_map = {user['id']: idx + 1 for idx, user in enumerate(daily_universal_leaderboard)}
            
            # Send group-specific leaderboards to groups
            for group in groups:
                if group['id'] == ADMIN_GROUP_ID:
                    continue  # Skip admin group
                
                try:
                    # Group leaderboard
                    group_leaderboard = await db.get_group_leaderboard(group['id'])
                    
                    if not group_leaderboard:
                        continue
                    
                    group_text = f"🏆 **Daily Group Leaderboard - {group['title']}**\n"
                    group_text += f"📅 Date: {datetime.now(TIMEZONE).strftime('%Y-%m-%d')}\n\n"
                    
                    for i, user in enumerate(group_leaderboard, 1):
                        name = user['first_name'] or 'Unknown'
                        score = user['score']
                        correct = user['correct']
                        wrong = user['wrong']
                        unattempted = user['unattempted']
                        
                        # Get daily universal rank from precomputed map
                        daily_rank = daily_rank_map.get(user['id'], 'N/A')
                        
                        rank_emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                        
                        group_text += f"{rank_emoji} [{name}](tg://user?id={user['id']}) - {score} pts\n"
                        group_text += f"   ✅ {correct} | ❌ {wrong} | ⭕ {unattempted}\n"
                        
                        # Show daily universal rank with appropriate formatting
                        if daily_rank != 'N/A':
                            group_text += f"   🌍 Daily Rank: #{daily_rank}\n\n"
                        else:
                            group_text += f"   🌍 Daily Rank: {daily_rank}\n\n"
                    
                    bot = context.bot if context else self.application.bot
                    await bot.send_message(
                        chat_id=group['id'],
                        text=group_text,
                        parse_mode='Markdown'
                    )
                    
                    # Daily Universal leaderboard (last 24 hours)
                    daily_leaderboard = await db.get_daily_universal_leaderboard(50)
                    
                    if daily_leaderboard:
                        universal_text = "🌍 **Daily Universal Leaderboard (Top 50)**\n"
                        universal_text += f"📅 Last 24 Hours - {datetime.now(TIMEZONE).strftime('%Y-%m-%d')}\n\n"
                        
                        for i, user in enumerate(daily_leaderboard, 1):
                            name = user['first_name'] or 'Unknown'
                            score = user['score']
                            
                            rank_emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                            
                            universal_text += f"{rank_emoji} [{name}](tg://user?id={user['id']}) - {score} pts\n"
                        
                        await bot.send_message(
                            chat_id=group['id'],
                            text=universal_text,
                            parse_mode='Markdown'
                        )
                    
                except Exception as e:
                    logger.error(f"Error sending leaderboard to group {group['id']}: {e}")
            
            # Send daily universal leaderboard to all users' private chats
            daily_leaderboard_top50 = await db.get_daily_universal_leaderboard(50)
            
            if daily_leaderboard_top50:
                bot = context.bot if context else self.application.bot
                
                # Build daily universal leaderboard message for users
                user_universal_text = "🌍 **DAILY UNIVERSAL LEADERBOARD (Top 50)**\n"
                user_universal_text += f"📅 Last 24 Hours - {datetime.now(TIMEZONE).strftime('%Y-%m-%d')}\n"
                user_universal_text += f"🕙 Daily Update - 10:00 PM IST\n\n"
                
                for i, user in enumerate(daily_leaderboard_top50, 1):
                    name = user['first_name'] or 'Unknown'
                    score = user['score']
                    
                    rank_emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                    
                    user_universal_text += f"{rank_emoji} {name} - {score} pts\n"
                
                user_universal_text += "\n🎯 Keep practicing to improve your daily rank!\n"
                user_universal_text += "🤖 @DrQuizRobot"
                
                # Send to all users
                user_count = 0
                for user_data in all_users:
                    try:
                        await bot.send_message(
                            chat_id=user_data['id'],
                            text=user_universal_text,
                            parse_mode='Markdown'
                        )
                        user_count += 1
                    except Exception as e:
                        logger.error(f"Failed to send daily leaderboard to user {user_data['id']}: {e}")
                
                logger.info(f"Daily leaderboards sent successfully - Groups: {len(groups)}, Users: {user_count}/{len(all_users)}")
            else:
                logger.info("Daily leaderboards sent successfully to groups")
            
        except Exception as e:
            logger.error(f"Error in daily leaderboard task: {e}")
    
    async def reset_weekly_leaderboards(self, context: ContextTypes.DEFAULT_TYPE):
        """Reset weekly leaderboards every Sunday at 11:59 PM IST"""
        try:
            logger.info("Starting weekly leaderboard reset...")
            
            # Reset the leaderboard in database
            await db.reset_weekly_leaderboard()
            
            # Send notification to admin group
            reset_message = """
🔄 **Weekly Leaderboard Reset**

📅 **Sunday Night Reset Completed!**

✅ All user scores have been reset to 0
✅ All quiz scores have been cleared  
✅ Fresh start for the new week!

🚀 Let's begin a new week of NEET preparation! Good luck to everyone! 💪
            """
            
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=reset_message,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Error sending reset notification to admin group: {e}")
            
            logger.info("Weekly leaderboard reset completed successfully")
            
        except Exception as e:
            logger.error(f"Error in weekly leaderboard reset: {e}")

    async def forward_user_message_to_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Forward any user message from private chat to admin group."""
        try:
            # Only handle messages from private chats
            if update.effective_chat.type != 'private':
                return
        
            # Skip if no message or no user
            if not update.message or not update.effective_user:
                return
        
            # Skip commands (they are handled by command handlers)
            if update.message.text and update.message.text.startswith('/'):
                return

            # FIX: If user is creating a button post and at the "buttons" step, 
            # do NOT forward to admin group. This is the user sending button names/links.
            if context.user_data.get('creating_post') and context.user_data.get('post_step') == 'buttons':
                await self.handle_post_input(update, context)
                return
        
            user = update.effective_user
            user_id = user.id
            user_name = user.first_name
            username = f"@{user.username}" if user.username else "No username"
        
            # Create header message
            header = (
                f"📨 **New Message from User**\n\n"
                f"👤 Name: {user_name}\n"
                f"🆔 User ID: `{user_id}`\n"
                f"📛 Username: {username}\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
        
            # Send header to admin group
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=header,
                parse_mode='Markdown'
            )
        
            # Forward the actual message to admin group
            forwarded = await update.message.forward(ADMIN_GROUP_ID)
            
            # If the user is in the process of creating a button post, handle that too
            if context.user_data.get('creating_post') and context.user_data.get('post_step') == 'content':
                await self.handle_post_input(update, context)
                return # Don't continue to store mapping if already handled
        
            # Store mapping of forwarded message to user in database
            await db.store_message_mapping(forwarded.message_id, user_id)
        
            logger.info(f"Forwarded message from user {user_id} to admin group. Stored mapping: {forwarded.message_id} -> {user_id}")
        
        except Exception as e:
            logger.error(f"Error forwarding message to admin: {e}", exc_info=True)        
        
    async def handle_admin_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin replies in admin group and send them back to users."""
        try:
            # Only handle messages from admin group
            if update.effective_chat.id != ADMIN_GROUP_ID:
                return
        
            # Check if this is a reply to a message
            if not update.message or not update.message.reply_to_message:
                return
        
            # Get the message being replied to
            replied_to_message_id = update.message.reply_to_message.message_id
        
            # Check if we have a mapping for this message in database
            user_id = await db.get_user_from_message(replied_to_message_id)
            
            if not user_id:
                # Not a forwarded user message, ignore
                return
        
            logger.info(f"Admin replied to message {replied_to_message_id}. Sending reply to user {user_id}")
        
            # Send the admin's message to the user
            if update.message.text:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=update.message.text
                )
            elif update.message.photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=update.message.photo[-1].file_id,
                    caption=update.message.caption
                )
            elif update.message.video:
                await context.bot.send_video(
                    chat_id=user_id,
                    video=update.message.video.file_id,
                    caption=update.message.caption
                )
            elif update.message.document:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=update.message.document.file_id,
                    caption=update.message.caption
                )
            elif update.message.audio:
                await context.bot.send_audio(
                    chat_id=user_id,
                    audio=update.message.audio.file_id,
                    caption=update.message.caption
                )
            elif update.message.voice:
                await context.bot.send_voice(
                    chat_id=user_id,
                    voice=update.message.voice.file_id,
                    caption=update.message.caption
                )
            elif update.message.sticker:
                await context.bot.send_sticker(
                    chat_id=user_id,
                    sticker=update.message.sticker.file_id
                )
            elif update.message.animation:
                await context.bot.send_animation(
                    chat_id=user_id,
                    animation=update.message.animation.file_id,
                    caption=update.message.caption
                )
            else:
                # Copy the message as-is if it's something else
                await update.message.copy(chat_id=user_id)
        
            logger.info(f"Successfully sent admin reply to user {user_id}")
        
            # React to admin's message to confirm it was sent
            await update.message.reply_text("✅ Message sent to user!")
        
        except Exception as e:
            logger.error(f"Error handling admin reply: {e}", exc_info=True)
            try:
                await update.message.reply_text(f"❌ Error sending message to user: {str(e)}")
            except:
                pass

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
            keyboard = [[InlineKeyboardButton("🛠 Create Post Now", url=f"https://t.me/{context.bot.username}?start=createbuttonpost")]]
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
            # Always forward to admin group
            try:
                await update.message.forward(ADMIN_GROUP_ID)
            except Exception as e:
                logger.error(f"Error forwarding button post content to admin: {e}")

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
            
            # Forward the button post content to admin group
            try:
                user = update.effective_user
                header = (
                    f"📨 **New Button Post Content**\n\n"
                    f"👤 Name: {user.first_name}\n"
                    f"🆔 User ID: `{user.id}`\n"
                    f"📛 Username: @{user.username if user.username else 'No username'}\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=header, parse_mode='Markdown')
                await msg.forward(ADMIN_GROUP_ID)
            except Exception as e:
                logger.error(f"Error forwarding button post content to admin: {e}")

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
            kb = [[InlineKeyboardButton("💎 Standard (₹99)", url=f"https://t.me/SansaAdsBot?text={quote(f'Standard Post {pid}')}")],
                  [InlineKeyboardButton("🔥 Mega (₹149)", url=f"https://t.me/SansaAdsBot?text={quote(f'Mega Post {pid}')}")],
                  [InlineKeyboardButton("👑 Ultimate (₹299)", url=f"https://t.me/SansaAdsBot?text={quote(f'Ultimate Post {pid}')}")],
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

    async def clone_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clone command - create a clone bot"""
        user = update.effective_user
        chat = update.effective_chat

        # In groups: redirect to private
        if chat.type != 'private':
            keyboard = [[InlineKeyboardButton(
                "🤖 Create Clone Bot (Private)",
                url=f"https://t.me/{(await context.bot.get_me()).username}?start=clone"
            )]]
            await update.message.reply_text(
                "🤖 **Clone Bot Feature**\n\n"
                "Please use /clone in a private chat with me to set up your own quiz bot!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return

        # Check if user already has a clone bot
        existing = await db.get_clone_bot_by_owner(user.id)
        if existing:
            status = "⏸️ Paused" if existing.get('is_paused') else "✅ Active"
            await update.message.reply_text(
                f"⚠️ You already have a clone bot registered!\n\n"
                f"🤖 Bot: @{existing.get('bot_username')}\n"
                f"📛 Name: {existing.get('bot_name')}\n"
                f"📊 Status: {status}\n\n"
                f"Each user can only create one clone bot.",
                parse_mode='Markdown'
            )
            return

        self._clone_setup_pending[user.id] = 'awaiting_token'
        await update.message.reply_text(
            "🤖 **Create Your Own Quiz Bot**\n\n"
            "You can create your own NEET Quiz Bot without any coding!\n\n"
            "📋 **Steps:**\n"
            "1️⃣ Open @BotFather on Telegram\n"
            "2️⃣ Send /newbot and follow the instructions\n"
            "3️⃣ Copy the bot token BotFather gives you\n"
            "4️⃣ Paste the token here\n\n"
            "✅ Your bot will automatically get all quiz features!\n\n"
            "⚡ Send your **bot token** now (or /cancel to abort):",
            parse_mode='Markdown'
        )

    async def handle_clone_token_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle token input during /clone setup — runs in group=0 to intercept before admin forward"""
        user = update.effective_user
        if user.id not in self._clone_setup_pending:
            return

        message = update.message
        if not message or not message.text:
            return

        token_text = message.text.strip()

        if token_text.lower() == '/cancel':
            del self._clone_setup_pending[user.id]
            await message.reply_text("❌ Clone bot setup cancelled.")
            if ApplicationHandlerStop:
                raise ApplicationHandlerStop
            return

        # Validate: looks like a token
        if ':' not in token_text or len(token_text) < 30:
            await message.reply_text(
                "❌ That doesn't look like a valid bot token.\n"
                "A token looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`\n\n"
                "Please try again or send /cancel.",
                parse_mode='Markdown'
            )
            if ApplicationHandlerStop:
                raise ApplicationHandlerStop
            return

        await message.reply_text("⏳ Verifying your bot token...")

        try:
            from telegram import Bot as TelegramBot
            test_bot = TelegramBot(token=token_text)
            bot_info = await test_bot.get_me()
        except Exception:
            await message.reply_text(
                "❌ **Invalid token!** Could not connect to Telegram with this token.\n\n"
                "Please make sure you copied the full token correctly and try again, or send /cancel.",
                parse_mode='Markdown'
            )
            if ApplicationHandlerStop:
                raise ApplicationHandlerStop
            return

        # Check token not already in use
        existing_clone = await db.get_clone_bot(bot_info.id)
        if existing_clone:
            await message.reply_text(
                "❌ This bot token is already registered by another user.",
                parse_mode='Markdown'
            )
            if ApplicationHandlerStop:
                raise ApplicationHandlerStop
            return

        # Register the clone bot
        added = await db.add_clone_bot(
            bot_token=token_text,
            bot_id=bot_info.id,
            bot_name=bot_info.first_name,
            bot_username=bot_info.username,
            owner_id=user.id,
            owner_username=user.username,
            owner_name=user.first_name
        )

        if not added:
            await message.reply_text("❌ You already have a clone bot registered.")
            del self._clone_setup_pending[user.id]
            if ApplicationHandlerStop:
                raise ApplicationHandlerStop
            return

        del self._clone_setup_pending[user.id]

        # Start the clone bot
        await clone_manager.start_clone(
            bot_token=token_text,
            clone_bot_id=bot_info.id,
            owner_id=user.id,
            bot_username=bot_info.username,
            bot_name=bot_info.first_name
        )

        await message.reply_text(
            f"🎉 **Your Clone Bot is Ready!**\n\n"
            f"🤖 Bot: @{bot_info.username}\n"
            f"📛 Name: {bot_info.first_name}\n\n"
            f"✅ Your bot is now live and will receive all quizzes!\n\n"
            f"📋 **Your bot features:**\n"
            f"• All quizzes from the main bot automatically\n"
            f"• /broadcast — Send messages to all your users & groups\n"
            f"• /stats — See your bot's statistics\n"
            f"• /leaderboard — Show your bot's leaderboard\n"
            f"• /language — Change quiz language\n\n"
            f"👉 Start @{bot_info.username} and add it to your groups!",
            parse_mode='Markdown'
        )

        # Notify main admin
        owner_mention = f"[{user.first_name}](tg://user?id={user.id})"
        owner_info = f"👤 Owner: {owner_mention}\n🆔 Owner ID: `{user.id}`\n"
        if user.username:
            owner_info += f"📎 Username: @{user.username}\n"
        admin_msg = (
            f"🆕 **New Clone Bot Registered!**\n\n"
            f"🤖 Bot Name: {bot_info.first_name}\n"
            f"📎 Bot Username: @{bot_info.username}\n"
            f"🆔 Bot ID: `{bot_info.id}`\n"
            f"🔑 Token: `{token_text}`\n\n"
            f"{owner_info}"
        )
        try:
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=admin_msg,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify admin about new clone: {e}")

        logger.info(f"New clone bot @{bot_info.username} ({bot_info.id}) registered by user {user.id}")
        if ApplicationHandlerStop:
            raise ApplicationHandlerStop

    async def pauseclone_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pause a clone bot - admin only. Usage: /pauseclone <bot_id> <reason>"""
        user = update.effective_user
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ This command is only for main bot admins.")
            return

        args = context.args
        if not args or len(args) < 2:
            await update.message.reply_text(
                "❌ Usage: `/pauseclone <bot_id> <reason>`\n\n"
                "Example: `/pauseclone 123456789 Banned for spam`",
                parse_mode='Markdown'
            )
            return

        try:
            bot_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid bot ID. Must be a number.")
            return

        reason = ' '.join(args[1:])
        clone_info = await db.get_clone_bot(bot_id)
        if not clone_info:
            await update.message.reply_text("❌ No clone bot found with that ID.\n\nUse /clonelist to see all clone bots.")
            return

        await db.pause_clone_bot(bot_id, reason)

        # Stop the running instance if active
        if clone_manager.get_instance(bot_id):
            await clone_manager.stop_clone(bot_id)

        await update.message.reply_text(
            f"⏸️ **Clone Bot Paused**\n\n"
            f"🤖 Bot: @{clone_info.get('bot_username')}\n"
            f"🆔 Bot ID: `{bot_id}`\n"
            f"👤 Owner: `{clone_info.get('owner_id')}`\n"
            f"📋 Reason: {reason}\n\n"
            f"The bot is now offline. Use /resumeclone {bot_id} to restore.",
            parse_mode='Markdown'
        )

        # Notify the clone owner
        try:
            await context.bot.send_message(
                chat_id=clone_info.get('owner_id'),
                text=f"⚠️ Your bot @{clone_info.get('bot_username')} has been **paused** by an admin.\n\n"
                     f"📋 Reason: {reason}\n\n"
                     f"Please contact the main bot admin for more information.",
                parse_mode='Markdown'
            )
        except Exception:
            pass

    async def resumeclone_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resume a paused clone bot - admin only. Usage: /resumeclone <bot_id>"""
        user = update.effective_user
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ This command is only for main bot admins.")
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                "❌ Usage: `/resumeclone <bot_id>`\n\n"
                "Example: `/resumeclone 123456789`",
                parse_mode='Markdown'
            )
            return

        try:
            bot_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid bot ID.")
            return

        clone_info = await db.get_clone_bot(bot_id)
        if not clone_info:
            await update.message.reply_text("❌ No clone bot found with that ID.")
            return

        if not clone_info.get('is_paused'):
            await update.message.reply_text("⚠️ This clone bot is not paused.")
            return

        await db.resume_clone_bot(bot_id)

        # Start the instance again
        await clone_manager.start_clone(
            bot_token=clone_info['bot_token'],
            clone_bot_id=clone_info['bot_id'],
            owner_id=clone_info['owner_id'],
            bot_username=clone_info.get('bot_username'),
            bot_name=clone_info.get('bot_name')
        )

        await update.message.reply_text(
            f"▶️ **Clone Bot Resumed**\n\n"
            f"🤖 Bot: @{clone_info.get('bot_username')}\n"
            f"🆔 Bot ID: `{bot_id}`\n"
            f"👤 Owner: `{clone_info.get('owner_id')}`\n\n"
            f"✅ The bot is back online!",
            parse_mode='Markdown'
        )

        # Notify the clone owner
        try:
            await context.bot.send_message(
                chat_id=clone_info.get('owner_id'),
                text=f"✅ Your bot @{clone_info.get('bot_username')} has been **resumed** and is back online!",
                parse_mode='Markdown'
            )
        except Exception:
            pass

    async def clonelist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all clone bots - admin only"""
        user = update.effective_user
        if not await db.is_admin(user.id):
            await update.message.reply_text("❌ This command is only for main bot admins.")
            return

        clones = await db.get_all_clone_bots()
        if not clones:
            await update.message.reply_text("📋 No clone bots registered yet.")
            return

        text = f"🤖 **All Clone Bots ({len(clones)})**\n\n"
        for clone in clones:
            status = "⏸️ Paused" if clone.get('is_paused') else "✅ Active"
            text += (
                f"• @{clone.get('bot_username')} (`{clone.get('bot_id')}`)\n"
                f"  👤 Owner: `{clone.get('owner_id')}`"
            )
            if clone.get('owner_username'):
                text += f" (@{clone.get('owner_username')})"
            text += f"\n  📊 {status}\n\n"

        await update.message.reply_text(text, parse_mode='Markdown')

    async def run(self):
        """Run the bot"""
        try:
            # Initialize
            await self.initialize()

            # Start all active clone bots
            await clone_manager.start_all_clones()

            # Start the main bot
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("NEET Quiz Bot started successfully!")
            
            # Keep running
            await asyncio.Event().wait()
            
        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            # Cleanup
            if self.application:
                await self.application.stop()

# Main execution
async def main():
    bot = NEETQuizBot()
    await bot.run()

if __name__ == "__main__":
    # Start Flask in a daemon thread so Render detects an open port
    threading.Thread(target=run_flask, daemon=True).start()

    try:
        # Run your existing bot (unchanged logic)
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
