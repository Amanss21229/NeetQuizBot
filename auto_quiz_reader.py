import logging
import os
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession


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
    Isolated MTProto user-account client for the automatic quiz system.

    Phase 1 responsibility:
    - securely connect an authorized Telegram user session
    - verify that the session is a real user account
    - keep MTProto completely isolated from the existing Bot API system

    It does NOT vote on quizzes yet.
    """

    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.started = False

    def _load_config(self):
        api_id_raw = os.environ.get("TG_API_ID", "").strip()
        api_hash = os.environ.get("TG_API_HASH", "").strip()
        session_string = os.environ.get(
            "TG_USER_SESSION",
            ""
        ).strip()

        if not api_id_raw:
            raise RuntimeError("TG_API_ID is missing")

        if not api_hash:
            raise RuntimeError("TG_API_HASH is missing")

        if not session_string:
            raise RuntimeError("TG_USER_SESSION is missing")

        try:
            api_id = int(api_id_raw)
        except ValueError:
            raise RuntimeError(
                "TG_API_ID must be a valid integer"
            )

        return api_id, api_hash, session_string

    async def start(self):
        """
        Start the isolated Telegram user client.

        Failure here must never terminate the main NEET quiz bot.
        """

        if self.started:
            return True

        api_id, api_hash, session_string = self._load_config()

        self.client = TelegramClient(
            StringSession(session_string),
            api_id,
            api_hash,
            auto_reconnect=True,
            connection_retries=5,
            retry_delay=3,
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

        # Security:
        # Never log phone number, API hash or session string.
        logger.info(
            "Auto Quiz Reader connected successfully | "
            "telegram_user_id=%s",
            me.id
        )

        return True

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

        logger.info("Auto Quiz Reader stopped")


auto_quiz_reader = AutoQuizReader()
