import asyncio
import logging
import os
import random
from datetime import datetime, timezone, time
from typing import Dict, List

import pytz
from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    BotCommand,
    Poll,
    PollAnswer,
    ChatMember,
    Message
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PollAnswerHandler,
    ChatMemberHandler,
    ContextTypes,
    filters
)

from models import db
# Add these imports (put them near the top with other imports)
from flask import Flask
import threading
from deep_translator import GoogleTranslator


# Bot configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required. Please set it with your bot token from @BotFather")
ADMIN_GROUP_ID = -1003009412065
TIMEZONE = pytz.timezone('Asia/Kolkata')

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

    
    def _register_handlers(self):
        """Register all bot handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("refresh", self.refresh_command))
        self.application.add_handler(CommandHandler("donate", self.donate_command))
        self.application.add_handler(CommandHandler("developer", self.developer_command))
        self.application.add_handler(CommandHandler("leaderboard", self.leaderboard_command))
        self.application.add_handler(CommandHandler("sol", self.get_solution))
      
        # Admin commands
        self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
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
        
        # Poll and quiz handlers
        self.application.add_handler(MessageHandler(filters.POLL, self.handle_quiz))
        self.application.add_handler(MessageHandler(filters.TEXT & filters.REPLY, self.handle_reply_to_poll))
        self.application.add_handler(PollAnswerHandler(self.handle_poll_answer))
        
        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        
        # Chat member handler for new groups
        self.application.add_handler(ChatMemberHandler(
            self.handle_chat_member_update, 
            ChatMemberHandler.MY_CHAT_MEMBER
        ))
        
        # Track any group where bot sees activity
        self.application.add_handler(MessageHandler(filters.ALL, self.track_groups))
        
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
            BotCommand("donate", "Support the bot"),
            BotCommand("developer", "Meet the developer"),
            BotCommand("leaderboard", "Show group leaderboard"),
            BotCommand("sol", "Show Detail Solution"),
        ]
        
        admin_commands = [
            BotCommand("broadcast", "Broadcast message"),
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
        ]
        
        await self.application.bot.set_my_commands(commands)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        chat = update.effective_chat
        
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
        """Automatically register any group where the bot sees activity"""
        chat = update.effective_chat
        if chat and chat.type in ["group", "supergroup"]:
            # Add to in-memory cache (works even if DB fails)
            self.groups_cache[chat.id] = {
                "title": chat.title or "Unknown Group",
                "type": chat.type
            }
            # Try to add to database (may fail if DB is down)
            try:
                await db.add_group(chat.id, chat.title or "Unknown Group", chat.type)
            except Exception as e:
                logger.warning(f"Failed to add group to database: {e}")
    
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
        """Forward quiz to all groups"""
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
            
            # Get all active groups
            groups = await db.get_all_groups()
            sent_count = 0
            
            poll = quiz_data['poll_object']
            options = quiz_data['options']
            
            for group in groups:
                if group['id'] != ADMIN_GROUP_ID:  # Don't send back to admin group
                    try:
                        # Get language preference for this group
                        group_language = await db.get_group_language(group['id'])
                        
                        # Determine question and options based on language
                        quiz_question = poll.question
                        quiz_options = options
                        
                        # Translate to Hindi if needed
                        if group_language == 'hindi':
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
                                    logger.info(f"Translated quiz {quiz_id} to Hindi for group {group['id']}")
                                    
                                except Exception as translation_error:
                                    # Fallback to English if translation fails
                                    logger.error(f"Translation error for quiz {quiz_id}: {translation_error}")
                                    logger.warning(f"Falling back to English for group {group['id']}")
                                    quiz_question = poll.question
                                    quiz_options = options
                        
                        # Send new poll (not forward) with is_anonymous=False
                        sent_message = await context.bot.send_poll(
                            chat_id=group['id'],
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
                            'group_id': group['id'],
                            'message_id': sent_message.message_id
                        }

                        # ✅ Mapping store karo for /sol
                        self.quiz_mapping[sent_message.message_id] = quiz_id

                        
                        sent_count += 1
                        logger.info(f"✅ Quiz sent to group {group['id']} with poll_id {sent_message.poll.id}")
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to send quiz to group {group['id']}: {e}")
            
            if sent_count > 0:
                # Send confirmation to admin
                option_letter = chr(65 + correct_option)  # Convert to A, B, C, D
                confirmation = f"🎯 **Quiz Forwarded Successfully!**\n\n📊 Sent to {sent_count} groups\n✅ Correct Answer: **{option_letter}**"
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=confirmation,
                    parse_mode='Markdown'
                )
                logger.info(f"🎯 Quiz '{poll.question[:50]}...' sent to {sent_count} groups successfully!")
            else:
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text="⚠️ Quiz not sent to any groups - No active groups found!",
                    parse_mode='Markdown'
                )
                logger.warning("⚠️ Quiz not sent to any groups")
        
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
        confirmation_text = f"✅ **Correct Answer Set!**\n\n🎯 Quiz: {reply_to_message.poll.question[:50]}...\n✅ Correct Option: **{option_letter}**\n\n⏰ **Quiz will be forwarded to all groups in 30 seconds!**"
        
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
        await update.message.reply_text("🔄 Bot refreshed successfully! All systems operational. 🚀")
    
    async def donate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /donate command"""
        user = update.effective_user
        
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
    
    async def leaderboard_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /leaderboard command - show current group leaderboard with universal ranks"""
        chat = update.effective_chat
        
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
        """Handle /broadcast command (admin only)"""
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
            broadcast_count = 0
            
            # Broadcast to all groups
            for group in groups:
                try:
                    await context.bot.copy_message(
                        chat_id=group['id'],
                        from_chat_id=replied_message.chat_id,
                        message_id=replied_message.message_id
                    )
                    broadcast_count += 1
                except Exception as e:
                    logger.error(f"Failed to broadcast to group {group['id']}: {e}")
            
            await update.message.reply_text(
                f"✅ Message broadcast to {broadcast_count} groups successfully!"
            )
            
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            await update.message.reply_text("❌ Error occurred during broadcast.")

    async def emergency_broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /emergencybroadcast or /ebroadcast command - works WITHOUT database"""
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
        
            broadcast_count = 0
            failed_count = 0
        
            status_msg = await update.message.reply_text(
                f"🔄 **Emergency Broadcast Started**\n\n"
                f"📊 Groups in cache: {len(self.groups_cache)}\n"
                f"⏳ Sending messages..."
            )
        
            # Broadcast to all groups in cache
            for group_id, group_info in self.groups_cache.items():
                try:
                    await context.bot.copy_message(
                        chat_id=group_id,
                        from_chat_id=replied_message.chat_id,
                        message_id=replied_message.message_id
                    )
                    broadcast_count += 1
                except Exception as e:
                    logger.error(f"Failed to emergency broadcast to group {group_id}: {e}")
                    failed_count += 1
        
            # Update status
            await status_msg.edit_text(
                f"✅ **Emergency Broadcast Complete!**\n\n"
                f"📊 **Statistics:**\n"
                f"   ✅ Successful: {broadcast_count}\n"
                f"   ❌ Failed: {failed_count}\n"
                f"   📝 Total groups in cache: {len(self.groups_cache)}\n\n"
                f"⚠️ **Note:** This used in-memory cache (no database required)"
            )
        
        except Exception as e:
            logger.error(f"Emergency broadcast error: {e}")
            await update.message.reply_text(
                f"❌ **Emergency broadcast failed!**\n\n"
                f"Error: {str(e)}"
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
        current_lang = await db.get_group_language(chat.id) if chat.type in ['group', 'supergroup'] else 'english'
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
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        query = update.callback_query
        await query.answer()
        
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
                
                # Set language preference
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
        """Send daily leaderboards at 10:00 PM IST"""
        try:
            groups = await db.get_all_groups()
            
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
                        
                        rank_emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                        
                        group_text += f"{rank_emoji} [{name}](tg://user?id={user['id']}) - {score} pts\n"
                        group_text += f"   ✅ {correct} | ❌ {wrong} | ⭕ {unattempted}\n\n"
                    
                    bot = context.bot if context else self.application.bot
                    await bot.send_message(
                        chat_id=group['id'],
                        text=group_text,
                        parse_mode='Markdown'
                    )
                    
                    # Universal leaderboard
                    universal_leaderboard = await db.get_universal_leaderboard(50)
                    
                    if universal_leaderboard:
                        universal_text = "🌍 **Universal Leaderboard (Top 50)**\n"
                        universal_text += f"📅 Date: {datetime.now(TIMEZONE).strftime('%Y-%m-%d')}\n\n"
                        
                        for i, user in enumerate(universal_leaderboard, 1):
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
            
            logger.info("Daily leaderboards sent successfully")
            
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

    async def run(self):
        """Run the bot"""
        try:
            # Initialize
            await self.initialize()
            
            
            # Start the bot
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
