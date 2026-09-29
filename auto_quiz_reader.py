import asyncio
import html
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from telethon import TelegramClient, events, types, functions
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from models import db


logger = logging.getLogger(__name__)


BIOLOGY_SOURCE_CHANNEL_ID = -1003677850351
PHYSICS_SOURCE_CHANNEL_ID = -1003205377239
CHEMISTRY_SOURCE_CHANNEL_ID = -1003545529979


SOURCE_CHANNELS = {
    BIOLOGY_SOURCE_CHANNEL_ID: "biology",
    CHEMISTRY_SOURCE_CHANNEL_ID: "chemistry",
    PHYSICS_SOURCE_CHANNEL_ID: "physics",
}

AIRA_ACTIVITY_GROUP_ID = -1003309585618

AIRA_ONLINE_IDLE_MINUTES = 30
AIRA_URGENT_COOLDOWN_MINUTES = 30

AIRA_WHATSAPP_NUMBER = "9153021229"

AIRA_URGENT_PATTERNS = (
    r"\burgent\b",
    r"\bemergency\b",
    r"\basap\b",
    r"\bimmediately\b",
    r"\bbahut\s+urgent\b",
    r"\bbahut\s+zaroori\b",
    r"\bbohot\s+zaroori\b",
    r"\bjaldi\s+reply\b",
    r"\bjaldi\s+response\b",
)

AIRA_URGENT_NEGATIONS = (
    "not urgent",
    "not an emergency",
    "no emergency",
    "urgent nahi",
    "emergency nahi",
)


class AutoQuizReader:
    """
    Isolated MTProto user-account reader.

    Responsibilities:
    - connect authorized Telegram user session
    - watch only configured source channels
    - detect native Telegram quiz polls
    - cast one vote
    - read Telegram's revealed correct answer
    - store quiz as READY in auto_quiz_bank

    It never distributes quizzes itself.
    """

    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.started = False
        self._processing = set()
        
        # AIRA Phase 2
        # Telegram user account connected through TG_USER_SESSION.
        # Used only to prevent self/Saved Messages processing.
        self.telegram_user_id: Optional[int] = None
        # Prevent two rapid messages from the same person from
        # racing topic creation / conversation-state updates.
        self._aira_user_locks = {}

    @staticmethod
    def _normalize_session_string(value: str) -> str:
        value = (value or "").strip()

        # Render copy/paste may accidentally include matching quotes.
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1].strip()

        # A StringSession must never contain line breaks/spaces.
        value = "".join(value.split())

        if not value:
            raise RuntimeError("TG_USER_SESSION is missing")

        # Telethon StringSession currently starts with its version marker.
        if value[0] != "1":
            raise RuntimeError(
                "TG_USER_SESSION has an invalid StringSession format"
            )

        # StringSession payload is URL-safe Base64.
        # Restore accidentally omitted trailing padding.
        payload = value[1:]
        missing_padding = (-len(payload)) % 4

        if missing_padding:
            payload += "=" * missing_padding

        return value[0] + payload

    def _load_config(self):
        api_id_raw = os.environ.get("TG_API_ID", "").strip()
        api_hash = os.environ.get("TG_API_HASH", "").strip()

        session_string = self._normalize_session_string(
            os.environ.get("TG_USER_SESSION", "")
        )

        if not api_id_raw:
            raise RuntimeError("TG_API_ID is missing")

        if not api_hash:
            raise RuntimeError("TG_API_HASH is missing")

        try:
            api_id = int(api_id_raw)
        except ValueError:
            raise RuntimeError(
                "TG_API_ID must be a valid integer"
            )

        return api_id, api_hash, session_string

    @staticmethod
    def _plain_text(value) -> str:
        if value is None:
            return ""

        text = getattr(value, "text", None)

        if text is not None:
            return str(text).strip()

        return str(value).strip()

    async def start(self):
        if self.started:
            return True

        api_id, api_hash, session_string = self._load_config()

        try:
            session = StringSession(session_string)
        except Exception as exc:
            raise RuntimeError(
                "TG_USER_SESSION is malformed. "
                "Generate a fresh Telethon StringSession."
            ) from exc

        self.client = TelegramClient(
            session,
            api_id,
            api_hash,
            auto_reconnect=True,
            connection_retries=5,
            retry_delay=3,
        )

        # Register before connecting so no new source update is missed.
        self.client.add_event_handler(
            self._handle_new_message,
            events.NewMessage()
        )

        await self.client.connect()

        if not await self.client.is_user_authorized():
            await self.client.disconnect()
            self.client = None

            raise RuntimeError(
                "TG_USER_SESSION is not authorized"
            )

        me = await self.client.get_me()

        if not me:
            await self.client.disconnect()
            self.client = None
            raise RuntimeError(
                "Unable to identify Telegram user session"
            )

        if getattr(me, "bot", False):
            await self.client.disconnect()
            self.client = None
            raise RuntimeError(
                "TG_USER_SESSION belongs to a bot, not a user"
            )

        # AIRA needs the connected personal account ID only for
        # safe self-message/Saved Messages exclusion.
        self.telegram_user_id = int(me.id)        

        self.started = True

        logger.info(
            "Auto Quiz Reader connected successfully | "
            "telegram_user_id=%s",
            me.id
        )

        return True

    def _get_aira_user_lock(self, user_id: int) -> asyncio.Lock:
        lock = self._aira_user_locks.get(user_id)

        if lock is None:
            lock = asyncio.Lock()
            self._aira_user_locks[user_id] = lock

        return lock


    @staticmethod
    def _aira_is_urgent(text: str) -> bool:
        clean = " ".join(
            (text or "").lower().split()
        )

        if not clean:
            return False

        if any(
            phrase in clean
            for phrase in AIRA_URGENT_NEGATIONS
        ):
            return False

        return any(
            re.search(pattern, clean, re.IGNORECASE)
            for pattern in AIRA_URGENT_PATTERNS
        )


    @staticmethod
    def _aira_dt(value):
        if not value:
            return None

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)


    @staticmethod
    def _aira_first_name(first_name: Optional[str]) -> str:
        name = (first_name or "").strip()

        if not name:
            return "there"

        # Avoid huge/malformed names inside templates.
        return name[:40]


    def _aira_offline_first_message(
        self,
        first_name: str
    ) -> str:
        safe_name = html.escape(first_name)

        return (
            "✦ <b>AIRA • Aman’s Personal Assistant</b>\n\n"
            f"Heyy {safe_name}! 🌷\n\n"
            "<blockquote>"
            "Aman abhi thode time ke liye <b>offline</b> hain. "
            "Aap apna message yahin send kar dijiye — "
            "main make sure karungi ki online aate hi "
            "woh ise check kar lein. ✨"
            "</blockquote>\n\n"
            "No worries, aapka message safely receive ho gaya hai. 🤍"
        )


    def _aira_offline_followup_message(
        self,
        first_name: str
    ) -> str:
        safe_name = html.escape(first_name)

        return (
            "✦ <b>AIRA</b>\n\n"
            f"Got it, {safe_name}! 🌷\n\n"
            "<blockquote>"
            "Aap baaki details bhi yahin send kar sakte hain. "
            "Main aapke messages Aman ke liye properly keep "
            "kar rahi hoon. ✨"
            "</blockquote>\n\n"
            "Woh online aate hi conversation check kar lenge. 🤍"
        )


    def _aira_online_message(
        self,
        first_name: str
    ) -> str:
        safe_name = html.escape(first_name)

        return (
            "✦ <b>AIRA • Aman’s Personal Assistant</b>\n\n"
            f"Heyy {safe_name}! 👋🏻\n\n"
            "<blockquote>"
            "Aman abhi <b>online</b> hain, bas messages ka "
            "traffic thoda high hai. 📩\n\n"
            "Aapka message receive ho gaya hai — thoda sa "
            "wait kariye, free hote hi woh personally reply "
            "karenge. ✨"
            "</blockquote>\n\n"
            "Thanks for being patient. 🤍"
        )


    def _aira_urgent_message(
        self,
        first_name: str
    ):
        safe_name = html.escape(first_name)

        prefilled = (
            f"Hi Aman, main {first_name} hoon. "
            "Maine aapko Telegram par message kiya hai. "
            "Matter urgent hai, isliye AIRA ke through "
            "WhatsApp par text kar raha/rahi hoon. "
            "Please free hone par check kar lena."
        )

        whatsapp_url = (
            "https://wa.me/91"
            + AIRA_WHATSAPP_NUMBER
            + "?text="
            + quote(prefilled)
        )

        safe_url = html.escape(
            whatsapp_url,
            quote=True
        )

        return (
            "🚨 <b>AIRA • Urgent Message</b>\n\n"
            f"{safe_name}, samajh gayi. 🤍\n\n"
            "<blockquote>"
            "Agar matter genuinely urgent hai aur Telegram "
            "reply ka wait possible nahi hai, aap Aman ko "
            "WhatsApp par <b>text message</b> kar sakte hain."
            "</blockquote>\n\n"
            f'💬 <a href="{safe_url}"><b>WhatsApp par text karein</b></a>\n\n'
            "<i>Please sirf genuine urgency me use karein — "
            "call nahi, text message only. ✨</i>"
        )    

    async def _aira_get_or_create_topic(
        self,
        user_id: int,
        first_name: str,
        username: Optional[str],
        existing_user: Optional[dict]
    ) -> Optional[int]:

        existing_topic_id = None

        if existing_user:
            existing_topic_id = existing_user.get(
                "topic_id"
            )

        if existing_topic_id:
            return int(existing_topic_id)

        if not self.client:
            return None

        username_text = (
            f"@{username}"
            if username
            else "no_username"
        )

        topic_name = (
            f"{first_name} • {username_text} • {user_id}"
        )[:128]

        try:
            inbox = await self.client.get_input_entity(
                AIRA_ACTIVITY_GROUP_ID
            )

            result = await self.client(
                functions.channels.CreateForumTopicRequest(
                    channel=inbox,
                    title=topic_name,
                    random_id=secrets.randbits(63)
                )
            )

            topic_id = None

            for update in getattr(
                result,
                "updates",
                []
            ):
                message = getattr(
                    update,
                    "message",
                    None
                )

                if message and getattr(
                    message,
                    "id",
                    None
                ):
                    topic_id = int(message.id)
                    break

            if not topic_id:
                raise RuntimeError(
                    "Telegram created topic but no topic ID "
                    "was returned"
                )

            await db.save_aira_topic(
                user_id=user_id,
                topic_id=topic_id,
                topic_name=topic_name
            )

            logger.info(
                "AIRA TOPIC CREATED | "
                "user_id=%s | topic_id=%s | topic=%s",
                user_id,
                topic_id,
                topic_name
            )

            return topic_id

        except Exception:
            logger.exception(
                "AIRA topic creation failed | user_id=%s",
                user_id
            )

            return None


    async def _aira_forward_to_inbox(
        self,
        event,
        topic_id: Optional[int],
        user_id: int
    ) -> bool:

        if not self.client or not topic_id:
            return False

        message = getattr(event, "message", None)

        if not message:
            return False

        try:
            source = await event.get_input_chat()

            destination = await self.client.get_input_entity(
                AIRA_ACTIVITY_GROUP_ID
            )

            await self.client(
                functions.messages.ForwardMessagesRequest(
                    from_peer=source,
                    id=[int(message.id)],
                    random_id=[secrets.randbits(63)],
                    to_peer=destination,
                    top_msg_id=int(topic_id),
                    drop_author=False
                )
            )

            logger.info(
                "AIRA MESSAGE FORWARDED | "
                "user_id=%s | message_id=%s | topic_id=%s",
                user_id,
                message.id,
                topic_id
            )

            return True

        except Exception:
            # Protected/non-forwardable messages must never
            # stop AIRA or Auto Quiz.
            logger.exception(
                "AIRA message forwarding failed | "
                "user_id=%s | message_id=%s | topic_id=%s",
                user_id,
                getattr(message, "id", None),
                topic_id
            )

            return False    

    async def _handle_aira_private_message(self, event) -> bool:
        """
        AIRA personal-DM pipeline.

        Isolated from the Auto Quiz source-channel pipeline.
        """

        try:
            if not getattr(event, "is_private", False):
                return False

            if getattr(event, "out", False):
                return False

            sender_id = getattr(
                event,
                "sender_id",
                None
            )

            if not sender_id:
                return False

            sender_id = int(sender_id)

            if (
                self.telegram_user_id is not None
                and sender_id == self.telegram_user_id
            ):
                return False

            sender = await event.get_sender()

            if not sender:
                return False

            if getattr(sender, "bot", False):
                return False

            if not isinstance(sender, types.User):
                return False

            lock = self._get_aira_user_lock(
                sender_id
            )

            async with lock:
                first_name_raw = (
                    getattr(
                        sender,
                        "first_name",
                        None
                    )
                    or ""
                ).strip() or None

                last_name = (
                    getattr(
                        sender,
                        "last_name",
                        None
                    )
                    or ""
                ).strip() or None

                username = (
                    getattr(
                        sender,
                        "username",
                        None
                    )
                    or ""
                ).strip() or None

                first_name = self._aira_first_name(
                    first_name_raw
                )

                # IMPORTANT:
                # Read OLD state BEFORE changing last_incoming_at.
                old_state = await db.get_aira_user(
                    sender_id
                )

                await db.upsert_aira_user(
                    user_id=sender_id,
                    first_name=first_name_raw,
                    last_name=last_name,
                    username=username
                )

                # ----------------------------------------------------
                # PHASE 4 — archive original incoming message
                # ----------------------------------------------------

                topic_id = await self._aira_get_or_create_topic(
                    user_id=sender_id,
                    first_name=first_name,
                    username=username,
                    existing_user=old_state
                )

                await self._aira_forward_to_inbox(
                    event=event,
                    topic_id=topic_id,
                    user_id=sender_id
                )

                # ----------------------------------------------------
                # PHASE 3 — reply decision
                # ----------------------------------------------------

                mode = await db.get_aira_mode()

                now = datetime.now(timezone.utc)

                previous_incoming = None
                previous_auto_reply = None
                previous_urgent_reply = None
                offline_stage = 0

                if old_state:
                    previous_incoming = self._aira_dt(
                        old_state.get(
                            "last_incoming_at"
                        )
                    )

                    previous_auto_reply = self._aira_dt(
                        old_state.get(
                            "last_auto_reply_at"
                        )
                    )

                    previous_urgent_reply = self._aira_dt(
                        old_state.get(
                            "last_urgent_reply_at"
                        )
                    )

                    offline_stage = int(
                        old_state.get(
                            "offline_reply_stage"
                        )
                        or 0
                    )

                idle_for = (
                    now - previous_incoming
                    if previous_incoming
                    else None
                )

                new_conversation = (
                    idle_for is None
                    or idle_for >= timedelta(
                        minutes=AIRA_ONLINE_IDLE_MINUTES
                    )
                )

                message = getattr(
                    event,
                    "message",
                    None
                )

                raw_text = (
                    getattr(
                        message,
                        "raw_text",
                        ""
                    )
                    or ""
                )

                urgent = self._aira_is_urgent(
                    raw_text
                )

                # Always record the incoming message.
                await db.update_aira_user_activity(
                    user_id=sender_id,
                    incoming=True
                )

                # ----------------------------------------------------
                # URGENT ESCALATION
                # ----------------------------------------------------

                urgent_allowed = (
                    urgent
                    and (
                        previous_urgent_reply is None
                        or (
                            now - previous_urgent_reply
                        ) >= timedelta(
                            minutes=AIRA_URGENT_COOLDOWN_MINUTES
                        )
                    )
                )

                if urgent_allowed:
                    try:
                        await event.reply(
                            self._aira_urgent_message(
                                first_name
                            ),
                            parse_mode="html",
                            link_preview=False
                        )

                        await db.update_aira_user_activity(
                            user_id=sender_id,
                            auto_reply=True,
                            urgent_reply=True
                        )

                        logger.info(
                            "AIRA URGENT REPLY SENT | "
                            "user_id=%s",
                            sender_id
                        )

                    except Exception:
                        logger.exception(
                            "AIRA urgent reply failed | "
                            "user_id=%s",
                            sender_id
                        )

                    return True

                # ----------------------------------------------------
                # OFFLINE MODE
                # ----------------------------------------------------

                if mode == "offline":

                    # 30+ minutes inactivity = fresh conversation.
                    if new_conversation:
                        offline_stage = 0

                        await db.set_aira_conversation_state(
                            sender_id,
                            offline_reply_stage=0,
                            reset_conversation=True
                        )

                    # First message.
                    if offline_stage <= 0:
                        try:
                            await event.reply(
                                self._aira_offline_first_message(
                                    first_name
                                ),
                                parse_mode="html",
                                link_preview=False
                            )

                            await db.update_aira_user_activity(
                                user_id=sender_id,
                                auto_reply=True
                            )

                            await db.set_aira_conversation_state(
                                sender_id,
                                offline_reply_stage=1
                            )

                            logger.info(
                                "AIRA OFFLINE FIRST REPLY SENT | "
                                "user_id=%s",
                                sender_id
                            )

                        except Exception:
                            logger.exception(
                                "AIRA offline first reply failed | "
                                "user_id=%s",
                                sender_id
                            )

                        return True

                    # Exactly one conversational follow-up.
                    if offline_stage == 1:
                        try:
                            await event.reply(
                                self._aira_offline_followup_message(
                                    first_name
                                ),
                                parse_mode="html",
                                link_preview=False
                            )

                            await db.update_aira_user_activity(
                                user_id=sender_id,
                                auto_reply=True
                            )

                            await db.set_aira_conversation_state(
                                sender_id,
                                offline_reply_stage=2
                            )

                            logger.info(
                                "AIRA OFFLINE FOLLOWUP SENT | "
                                "user_id=%s",
                                sender_id
                            )

                        except Exception:
                            logger.exception(
                                "AIRA offline followup failed | "
                                "user_id=%s",
                                sender_id
                            )

                        return True

                    # Third+ messages in same active conversation:
                    # archive them, but don't spam replies.
                    return True

                # ----------------------------------------------------
                # ONLINE MODE
                # ----------------------------------------------------

                if mode == "online":

                    # One reply only when this is a fresh conversation
                    # after >=30 minutes inactivity.
                    if new_conversation:
                        try:
                            await event.reply(
                                self._aira_online_message(
                                    first_name
                                ),
                                parse_mode="html",
                                link_preview=False
                            )

                            await db.update_aira_user_activity(
                                user_id=sender_id,
                                auto_reply=True
                            )

                            # Reset offline sequence for whenever
                            # owner later switches to offline.
                            await db.set_aira_conversation_state(
                                sender_id,
                                offline_reply_stage=0,
                                reset_conversation=True
                            )

                            logger.info(
                                "AIRA ONLINE REPLY SENT | "
                                "user_id=%s",
                                sender_id
                            )

                        except Exception:
                            logger.exception(
                                "AIRA online reply failed | "
                                "user_id=%s",
                                sender_id
                            )

                    return True

                return True

        except Exception:
            # Absolutely no AIRA failure may propagate into
            # existing Auto Quiz Reader.
            logger.exception(
                "AIRA private DM processing failed | "
                "sender_id=%s",
                getattr(
                    event,
                    "sender_id",
                    None
                )
            )

            return False    

    async def _handle_new_message(self, event):
        if not self.started:
            return

        chat_id = event.chat_id

        # ============================================================
        # ROUTE 1 — EXISTING AUTO QUIZ SOURCE CHANNELS
        # ============================================================
        #
        # Source channels always remain owned by the existing
        # Auto Quiz Reader flow below.
        #
        # Nothing in the existing quiz-processing code is changed.
        # ============================================================

        if chat_id in SOURCE_CHANNELS:
            pass

        # ============================================================
        # ROUTE 2 — AIRA PERSONAL PRIVATE DMs
        # ============================================================
        else:
            await self._handle_aira_private_message(event)
            return

        # ============================================================
        # EXISTING AUTO QUIZ CODE CONTINUES UNCHANGED BELOW
        # ============================================================

        message = event.message

        if not message:
            return

        media = getattr(message, "media", None)

        if not isinstance(media, types.MessageMediaPoll):
            return

        poll = getattr(media, "poll", None)

        if not poll or not getattr(poll, "quiz", False):
            return

        key = (int(chat_id), int(message.id))

        if key in self._processing:
            return

        self._processing.add(key)

        try:
            await self._process_quiz(
                chat_id=int(chat_id),
                message=message,
                subject=SOURCE_CHANNELS[chat_id]
            )

        except FloodWaitError as exc:
            logger.warning(
                "AUTO QUIZ MTProto FloodWait | chat=%s | "
                "message=%s | seconds=%s",
                chat_id,
                message.id,
                exc.seconds
            )

        except Exception:
            logger.exception(
                "AUTO QUIZ MTProto processing failed | "
                "chat=%s | message=%s",
                chat_id,
                message.id
            )

        finally:
            self._processing.discard(key)

    async def _process_quiz(
        self,
        chat_id: int,
        message,
        subject: str
    ):
        media = message.media
        poll = media.poll

        question = self._plain_text(poll.question)

        options = [
            self._plain_text(answer.text)
            for answer in poll.answers
        ]

        if not question or len(options) < 2:
            logger.warning(
                "AUTO QUIZ invalid MTProto poll ignored | "
                "chat=%s | message=%s",
                chat_id,
                message.id
            )
            return

        # First upsert PENDING.
        # This also removes the Bot API/MTProto arrival-order race.
        saved = await db.save_auto_quiz(
            subject=subject,
            source_chat_id=chat_id,
            source_message_id=message.id,
            source_poll_id=str(poll.id),
            question=question,
            options=options,
            correct_option=None
        )

        # If Bot API already knew the answer, do not vote again.
        if saved.get("status") == "ready":
            return

        input_chat = await message.get_input_chat()

        # A single vote is enough for Telegram Quiz mode to reveal
        # the correct answer to this user account.
        vote_option = poll.answers[0].option

        try:
            await self.client(
                functions.messages.SendVoteRequest(
                    peer=input_chat,
                    msg_id=message.id,
                    options=[vote_option]
                )
            )
        except Exception as exc:
            # It may already have been voted from this account.
            # Continue to fetch results before declaring failure.
            logger.info(
                "AUTO QUIZ vote returned %s | "
                "chat=%s | message=%s",
                type(exc).__name__,
                chat_id,
                message.id
            )

        correct_index = None

        # Telegram updates can arrive slightly after sendVote.
        for _ in range(6):
            await asyncio.sleep(1)

            refreshed = await self.client.get_messages(
                input_chat,
                ids=message.id
            )

            refreshed_media = getattr(
                refreshed,
                "media",
                None
            )

            if not isinstance(
                refreshed_media,
                types.MessageMediaPoll
            ):
                continue

            results = getattr(
                refreshed_media.results,
                "results",
                None
            ) or []

            correct_option_bytes = None

            for result in results:
                if getattr(result, "correct", False):
                    correct_option_bytes = result.option
                    break

            if correct_option_bytes is None:
                continue

            for index, answer in enumerate(
                refreshed_media.poll.answers
            ):
                if answer.option == correct_option_bytes:
                    correct_index = index
                    break

            if correct_index is not None:
                break

        if correct_index is None:
            logger.warning(
                "AUTO QUIZ answer not revealed; remains PENDING | "
                "subject=%s | chat=%s | message=%s",
                subject,
                chat_id,
                message.id
            )
            return

        ready = await db.mark_auto_quiz_ready(
            source_chat_id=chat_id,
            source_message_id=message.id,
            correct_option=correct_index
        )

        if ready:
            logger.info(
                "AUTO QUIZ READY | id=%s | subject=%s | "
                "chat=%s | message=%s | correct_option=%s",
                ready["id"],
                subject,
                chat_id,
                message.id,
                correct_index
            )

    async def stop(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                logger.exception(
                    "Error while disconnecting Auto Quiz Reader"
                )

        self.client = None
        self.started = False
        self.telegram_user_id = None
        self._aira_user_locks.clear()
        self._processing.clear()

        logger.info("Auto Quiz Reader stopped")


auto_quiz_reader = AutoQuizReader()
