import asyncio
import logging
import os
from typing import Optional

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

        self.started = True

        logger.info(
            "Auto Quiz Reader connected successfully | "
            "telegram_user_id=%s",
            me.id
        )

        return True

    async def _handle_new_message(self, event):
        if not self.started:
            return

        chat_id = event.chat_id

        if chat_id not in SOURCE_CHANNELS:
            return

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
        self._processing.clear()

        logger.info("Auto Quiz Reader stopped")


auto_quiz_reader = AutoQuizReader()
