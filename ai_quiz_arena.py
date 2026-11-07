"""Independent AI NEET Quiz Arena module for the main Telegram bot.

The arena deliberately uses its own tables and poll mappings; it does not
modify the legacy quiz scoring tables.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent,
)
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from private_ai.chat import ChatMessage

log = logging.getLogger(__name__)


def datetime_now_utc():
    return datetime.now(timezone.utc)

QUESTION_COUNTS = (5, 10, 15, 20, 25, 30, 35, 40, 45)
TIMES = (15, 30, 45, 60)


class QuizArena:
    def __init__(self, db, provider):
        self.db = db
        self.provider = provider
        self.configs: dict[int, dict[str, Any]] = {}
        self.polls: dict[str, dict[str, Any]] = {}
        self.session_locks: dict[str, asyncio.Lock] = {}
        self.preparation_tasks: dict[str, asyncio.Task] = {}
        self.preparation_errors: dict[str, str] = {}

    async def initialize(self):
        async with self.db.pool.acquire() as c:
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_question_bank (
                    id BIGSERIAL PRIMARY KEY,
                    chapter_key TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    language TEXT NOT NULL,
                    question TEXT NOT NULL,
                    options JSONB NOT NULL,
                    correct_index SMALLINT NOT NULL CHECK(correct_index BETWEEN 0 AND 3),
                    explanation TEXT NOT NULL DEFAULT '',
                    question_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    CONSTRAINT uq_arena_bank_chapter_language_hash
                    UNIQUE(chapter_key, language, question_hash)
                )
            """)
            # Migrate old uniqueness constraint.
            await c.execute("""
                ALTER TABLE arena_question_bank
                DROP CONSTRAINT IF EXISTS
                arena_question_bank_chapter_key_question_hash_key
            """)

            await c.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname =
                        'uq_arena_bank_chapter_language_hash'
                    ) THEN

                        ALTER TABLE arena_question_bank
                        ADD CONSTRAINT
                        uq_arena_bank_chapter_language_hash
                        UNIQUE (chapter_key, language, question_hash);

                    END IF;
                END
                $$;
            """)
            await c.execute("""
                CREATE OR REPLACE FUNCTION arena_question_bank_cap_guard()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                DECLARE
                    existing_count INTEGER;
                BEGIN

                    PERFORM pg_advisory_xact_lock(
                        hashtextextended(
                            NEW.chapter_key || ':' || NEW.language,
                            0
                        )
                    );

                    SELECT COUNT(*)
                    INTO existing_count
                    FROM arena_question_bank
                    WHERE chapter_key = NEW.chapter_key
                    AND language = NEW.language;

                    IF existing_count >= 1000 THEN
                        RETURN NULL;
                    END IF;

                    RETURN NEW;

                END;
                $$;
            """)

            await c.execute("""
                DROP TRIGGER IF EXISTS
                trg_arena_question_bank_cap
                ON arena_question_bank
            """)

            await c.execute("""
                CREATE TRIGGER trg_arena_question_bank_cap
                BEFORE INSERT ON arena_question_bank
                FOR EACH ROW
                EXECUTE FUNCTION arena_question_bank_cap_guard()
            """)
            await c.execute("ALTER TABLE arena_question_bank ADD COLUMN IF NOT EXISTS pyq_year INTEGER")
            await c.execute("ALTER TABLE arena_question_bank ADD COLUMN IF NOT EXISTS question_type TEXT NOT NULL DEFAULT 'single_correct'")
            await c.execute("ALTER TABLE arena_question_bank ADD COLUMN IF NOT EXISTS detailed_solution TEXT NOT NULL DEFAULT ''")
            await c.execute("CREATE INDEX IF NOT EXISTS idx_arena_bank_chapter ON arena_question_bank(chapter_key, language)")
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_chapter_sources (
                    id BIGSERIAL PRIMARY KEY,
                    chapter_key TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'english',
                    source_type TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await c.execute("""
                CREATE INDEX IF NOT EXISTS idx_arena_chapter_sources_lookup
                ON arena_chapter_sources(chapter_key,language,source_type)
            """)
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_sessions (
                    id TEXT PRIMARY KEY,
                    creator_id BIGINT NOT NULL,
                    chapter TEXT NOT NULL,
                    chapter_key TEXT NOT NULL,
                    language TEXT NOT NULL,
                    question_count INTEGER NOT NULL,
                    seconds INTEGER NOT NULL,
                    questions JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    current_index INTEGER NOT NULL DEFAULT -1,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    started_at TIMESTAMPTZ,
                    ended_at TIMESTAMPTZ
                )
            """)
            await c.execute("ALTER TABLE arena_sessions ADD COLUMN IF NOT EXISTS question_started_at TIMESTAMPTZ")
            await c.execute("ALTER TABLE arena_sessions ADD COLUMN IF NOT EXISTS session_code TEXT")
            await c.execute("ALTER TABLE arena_sessions ADD COLUMN IF NOT EXISTS invite_expires_at TIMESTAMPTZ")
            await c.execute("ALTER TABLE arena_sessions ADD COLUMN IF NOT EXISTS creator_chat_id BIGINT")
            await c.execute("ALTER TABLE arena_sessions ADD COLUMN IF NOT EXISTS creator_chat_type TEXT")
            await c.execute("ALTER TABLE arena_sessions ADD COLUMN IF NOT EXISTS creator_chat_title TEXT")
            await c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_arena_session_code ON arena_sessions(session_code) WHERE session_code IS NOT NULL")
            # The old global lock blocked every Arena quiz, even in unrelated groups.
            # Group-level locks below enforce the intended one-active-session-per-group rule.
            await c.execute("DROP INDEX IF EXISTS uq_arena_single_active")
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_poll_map (
                    poll_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
                    chat_id BIGINT NOT NULL,
                    question_index INTEGER NOT NULL,
                    correct_index SMALLINT NOT NULL
                )
            """)
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_destinations (
                    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
                    chat_id BIGINT NOT NULL,
                    chat_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'joined',
                    PRIMARY KEY(session_id, chat_id)
                )
            """)
            await c.execute("ALTER TABLE arena_destinations ADD COLUMN IF NOT EXISTS username TEXT")
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_group_locks (
                    group_id BIGINT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
                    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await c.execute("""
                INSERT INTO arena_group_locks(group_id,session_id)
                SELECT DISTINCT ON (d.chat_id) d.chat_id,d.session_id
                FROM arena_destinations d
                JOIN arena_sessions s ON s.id=d.session_id
                WHERE d.chat_type IN ('group','supergroup')
                  AND d.status='joined'
                  AND s.status IN ('ready','active')
                ORDER BY d.chat_id,s.created_at DESC
                ON CONFLICT(group_id) DO NOTHING
            """)
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_invite_responses (
                    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
                    chat_id BIGINT NOT NULL,
                    response TEXT NOT NULL CHECK(response IN ('accepted','rejected')),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY(session_id, chat_id)
                )
            """)
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_waiting_members (
                    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY(session_id,user_id)
                )
            """)
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_participants (
                    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    joined_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY(session_id, user_id)
                )
            """)
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_answers (
                    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
                    chat_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    question_index INTEGER NOT NULL,
                    selected_index SMALLINT NOT NULL,
                    is_correct BOOLEAN NOT NULL,
                    points SMALLINT NOT NULL,
                    answered_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY(session_id, user_id, question_index)
                )
            """)
            await c.execute("""
                CREATE TABLE IF NOT EXISTS arena_invites (
                    token TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
                    creator_id BIGINT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

    async def schedule_recovery(self, job_queue):
        """Resume started sessions and expire unresumable drafts after restart."""
        async with self.db.pool.acquire() as c:
            # A process can die during generation; such sessions cannot safely resume.
            await c.execute(
                """UPDATE arena_sessions SET status='failed',ended_at=NOW()
                   WHERE status IN ('draft','generating')"""
            )
            await c.execute(
                """DELETE FROM arena_group_locks
                   WHERE session_id IN (
                       SELECT id FROM arena_sessions
                       WHERE status IN ('finished','cancelled','failed','expired')
                   )"""
            )
            rows = await c.fetch("SELECT id,status,current_index,seconds,question_started_at FROM arena_sessions WHERE status IN ('ready','active')")
        for row in rows:
            if row["status"] == "ready":
                delay = 5
            elif row["question_started_at"]:
                elapsed = (datetime_now_utc() - row["question_started_at"]).total_seconds()
                delay = max(0, int(row["seconds"] - elapsed))
            else:
                delay = 1
            job_queue.run_once(self._tick, when=delay, data={"session_id":row["id"]}, name=f"arena:{row['id']}:recovery")
        if not any(job.name == "arena_expiry_cleanup" for job in job_queue.jobs()):
            job_queue.run_repeating(
                self.cleanup_expired_sessions,
                interval=60,
                first=60,
                name="arena_expiry_cleanup",
            )

    async def cleanup_expired_sessions(self, context):
        async with self.db.pool.acquire() as c:
            expired = await c.fetch(
                """UPDATE arena_sessions
                   SET status='expired',ended_at=NOW()
                   WHERE status='draft' AND invite_expires_at IS NOT NULL
                     AND invite_expires_at <= NOW()
                   RETURNING id"""
            )
            if expired:
                ids = [row["id"] for row in expired]
                await c.execute(
                    "DELETE FROM arena_group_locks WHERE session_id=ANY($1::text[])",
                    ids,
                )

    @staticmethod
    def chapter_key(chapter: str) -> str:
        return re.sub(r"\s+", " ", chapter.strip().lower())

    async def command(self, update, context):
        user, chat = update.effective_user, update.effective_chat
        if not user or not chat:
            return
        chapter = " ".join(context.args or []).strip()
        if not chapter:
            await update.effective_message.reply_text("📚 Usage: /quiz Chapter Name\nExample: /quiz Cell The Unit of Life")
            return
        if len(chapter) > 100:
            await update.effective_message.reply_text("Chapter name 100 characters se chhota rakhein.")
            return
        async with self.db.pool.acquire() as c:
            existing_session = await c.fetchrow(
                """SELECT id,session_code,chapter,status FROM arena_sessions
                   WHERE creator_id=$1 AND status IN ('draft','generating','ready','active')
                   ORDER BY created_at DESC LIMIT 1""",
                user.id,
            )
        if existing_session:
            await update.effective_message.reply_text(
                f"⏳ You already have a {existing_session['status']} Arena session "
                f"for {existing_session['chapter']} (ID: {existing_session['session_code'] or existing_session['id']}). "
                "Finish it or use /stop before creating another."
            )
            return
        balance_row = await self.db.get_ai_credits(user.id)
        balance = int(balance_row["balance"]) if balance_row else 0
        await self.db.add_user(user.id, user.username, user.first_name, user.last_name)
        self.configs[user.id] = {"chapter": chapter, "chat_id": chat.id, "chat_type": chat.type, "title": chat.title or user.first_name, "username": getattr(chat, "username", None), "language": None, "count": None, "seconds": None}
        kb = [
            [InlineKeyboardButton("🇮🇳 Hindi", callback_data="arena:lang:hindi"), InlineKeyboardButton("🇬🇧 English", callback_data="arena:lang:english")],
        ]
        count_row = []
        for n in QUESTION_COUNTS:
            count_row.append(InlineKeyboardButton(str(n), callback_data=f"arena:count:{n}"))
            if len(count_row) == 3:
                kb.append(count_row)
                count_row = []
        if count_row:
            kb.append(count_row)
        kb.append([InlineKeyboardButton(f"⏱ {s} sec", callback_data=f"arena:time:{s}") for s in TIMES])
        await update.effective_message.reply_text(
            f"🧠 *NEET QUIZ ARENA*\n\n📖 Chapter: *{chapter}*\n💳 Available credits: *{balance}*\n\n1) Choose language\n2) Choose number of questions\n3) Choose time per question\n\n1 credit = 5 questions. A {45}-question quiz costs 9 credits.",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    async def callback(self, q, context) -> bool:
        data = q.data or ""
        if not data.startswith("arena:"):
            return False
        parts = data.split(":")
        action = parts[1]
        user_id = q.from_user.id
        if action in ("lang", "count", "time"):
            cfg = self.configs.get(user_id)
            if not cfg:
                await q.answer("Configuration expired. Run /quiz again.", show_alert=True); return True
            if action == "lang": cfg["language"] = parts[2]
            elif action == "count": cfg["count"] = int(parts[2])
            elif action == "time": cfg["seconds"] = int(parts[2])
            await q.answer("Saved")
            if all(cfg.get(k) for k in ("language", "count", "seconds")):
                bank_total = await self._bank_count(cfg["chapter"], cfg["language"])
                if int(cfg["count"]) > 20 and bank_total < 1000:
                    cfg["count"] = None
                    limited = [
                        [InlineKeyboardButton(str(n), callback_data=f"arena:count:{n}")]
                        for n in (5, 10, 15, 20)
                    ]
                    await context.bot.send_message(
                        cfg["chat_id"],
                        "🧪 Beta limit: is chapter/language bank mein abhi 1,000 approved questions complete nahi hue hain. AI generation ke liye maximum 20 questions select karein.",
                        reply_markup=InlineKeyboardMarkup(limited),
                    )
                    return True
                try: await q.message.delete()
                except Exception: pass
                cost = math.ceil(cfg["count"] / 5)
                bal = await self.db.get_ai_credits(user_id)
                balance = int(bal["balance"]) if bal else 0
                if balance < cost:
                    await context.bot.send_message(cfg["chat_id"], f"❌ Insufficient credits. This quiz needs {cost} credits; your balance is {balance}.")
                    self.configs.pop(user_id, None); return True
                invite_token = uuid.uuid4().hex[:16]
                draft_id = uuid.uuid4().hex
                chapter_tag = re.sub(r"[^A-Z0-9]+", "", cfg["chapter"].upper())[:8] or "QUIZ"
                session_code = f"NQ-{chapter_tag}-{uuid.uuid4().int % 100000000:08d}"
                async with self.db.pool.acquire() as c:
                    await c.execute(
                        """INSERT INTO arena_sessions(
                               id,creator_id,chapter,chapter_key,language,
                               question_count,seconds,questions,status,
                               session_code,invite_expires_at,
                               creator_chat_id,creator_chat_type,creator_chat_title
                           )
                           VALUES($1,$2,$3,$4,$5,$6,$7,'[]'::jsonb,'draft',
                                  $8,NULL,$9,$10,$11)""",
                        draft_id, user_id, cfg["chapter"],
                        self.chapter_key(cfg["chapter"]), cfg["language"],
                        cfg["count"], cfg["seconds"], session_code,
                        cfg["chat_id"], cfg["chat_type"], cfg["title"]
                    )
                    await c.execute("INSERT INTO arena_invites(token,session_id,creator_id) VALUES($1,$2,$3)", invite_token, draft_id, user_id)
                cfg["session_code"] = session_code
                cfg["session_id"] = draft_id
                cfg["invite_token"] = invite_token
                cfg["cost"] = cost
                await context.bot.send_message(
                    cfg["chat_id"],
                    f"🧠 Preparing your NEET quiz...\\n\\n"
                    f"📖 {cfg['chapter']} · {cfg['language'].title()}\\n"
                    f"❓ {cfg['count']} questions · ⏱ {cfg['seconds']} sec/question\\n"
                    f"💳 Cost: {cost} credit(s)\\n"
                    f"🆔 Session ID: {session_code}\\n"
                    "Invitation and start buttons will appear after validation."
                )
                # Prepare and validate questions before presenting the final start/invite buttons.
                task = asyncio.create_task(self._prepare_questions(draft_id, cfg.copy(), context))
                self.preparation_tasks[draft_id] = task
            else:
                pass
            return True
        if action == "start":
            cfg = self.configs.get(user_id)
            if not cfg:
                await q.answer("Configuration expired. Run /quiz again.", show_alert=True)
                return True
            task = self.preparation_tasks.get(cfg.get("session_id"))
            if task and not task.done():
                await q.answer(
                    "Questions are still being prepared. Wait for the confirmation message, then press Done.",
                    show_alert=True
                )
                return True
            await q.answer("Starting quiz…")
            await self.start_session(user_id, cfg, context, q.message)
            return True
        if action == "solution":
            try:
                session_id = parts[2]
                question_index = int(parts[3])
                async with self.db.pool.acquire() as c:
                    row = await c.fetchrow(
                        "SELECT chapter,questions FROM arena_sessions WHERE id=$1",
                        session_id,
                    )
                if not row:
                    await q.answer("Solution is no longer available.", show_alert=True)
                    return True
                questions = row["questions"] or []
                if isinstance(questions, str):
                    questions = json.loads(questions)
                if question_index < 0 or question_index >= len(questions):
                    await q.answer("Solution is no longer available.", show_alert=True)
                    return True
                item = questions[question_index]
                solution = (item.get("detailed_solution") or item.get("explanation") or "Detailed solution is unavailable.")[:3800]
                await q.answer("Detailed solution")
                if q.message:
                    await q.message.reply_text(
                        f"📘 <b>Detailed Solution</b>\\n"
                        f"📖 {self._escape(row['chapter'])} · Q{question_index + 1}\\n\\n"
                        f"{self._escape(solution)}",
                        parse_mode="HTML",
                    )
                return True
            except Exception:
                log.exception("Arena detailed solution callback failed")
                await q.answer("Could not load the detailed solution.", show_alert=True)
                return True
        if action in ("accept", "reject"):
            session_id = parts[2]
            if action == "reject":
                try:
                    if q.message:
                        async with self.db.pool.acquire() as c:
                            await c.execute(
                                """INSERT INTO arena_invite_responses(session_id,chat_id,response)
                                   VALUES($1,$2,'rejected')
                                   ON CONFLICT(session_id,chat_id) DO UPDATE
                                   SET response='rejected',updated_at=NOW()""",
                                session_id, q.message.chat.id
                            )
                            await c.execute(
                                "UPDATE arena_destinations SET status='rejected' WHERE session_id=$1 AND chat_id=$2",
                                session_id, q.message.chat.id
                            )
                            await c.execute(
                                "DELETE FROM arena_waiting_members WHERE session_id=$1 AND chat_id=$2",
                                session_id, q.message.chat.id
                            )
                            await c.execute(
                                "DELETE FROM arena_group_locks WHERE session_id=$1 AND group_id=$2",
                                session_id, q.message.chat.id
                            )
                        await q.message.delete()
                    elif q.inline_message_id:
                        await context.bot.edit_message_text(
                            inline_message_id=q.inline_message_id,
                            text="❌ Invitation rejected."
                        )
                except Exception:
                    pass
                await q.answer("Invitation rejected")
                return True
            chat = q.message.chat if q.message else None
            
            if not chat:
                async with self.db.pool.acquire() as c:
                    display_code = await c.fetchval(
                        "SELECT session_code FROM arena_sessions WHERE id=$1",
                        session_id,
                    )
                await q.answer(
                    f"Group: send /accept {display_code or session_id} in the group. Private: start the bot, then send /accept {display_code or session_id} in its private chat.",
                    show_alert=True
                )
                return True
            if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                try:
                    member = await context.bot.get_chat_member(chat.id, user_id)
                    if member.status not in ("administrator", "creator"):
                        await q.answer("Only group admins can accept this invitation.", show_alert=True); return True
                except Exception:
                    await q.answer("Could not verify group admin rights.", show_alert=True); return True
            try:
                async with self.db.pool.acquire() as c:
                    row = await c.fetchrow(
                        """SELECT status,session_code,invite_expires_at FROM arena_sessions
                           WHERE id=$1 FOR UPDATE""", session_id
                    )
                    if not row or row["status"] not in ("draft", "generating", "ready") or (row["invite_expires_at"] and row["invite_expires_at"] <= datetime_now_utc()):
                        await q.answer("This quiz is no longer accepting destinations.", show_alert=True); return True
                    await self._register_destination(
                        c, session_id, chat.id, chat.type, chat.title or "Private",
                        getattr(chat, "username", None), user_id
                    )
                await q.answer("Quiz invitation accepted")
                await q.edit_message_text(
                    f"✅ Invitation accepted. Send this Session ID in this chat to join the waiting room:\n`{row['session_code'] or session_id}`",
                    parse_mode="Markdown"
                )
            except Exception as e:
                log.exception("arena invite accept failed: %s", e)
                await q.answer("Unable to accept this invitation.", show_alert=True)
            return True
        if action == "stop":
            await self.stop_for_chat(q.message.chat.id, user_id, context)
            await q.answer("Quiz stopped")
            return True
        return True

    async def _prepare_questions(self, session_id: str, cfg: dict, context=None):
        """Prepare and persist questions before the creator presses Done."""
        try:
            async with self.db.pool.acquire() as c:
                row = await c.fetchrow(
                    "SELECT status, questions FROM arena_sessions WHERE id=$1",
                    session_id,
                )
            if not row or row["status"] != "draft":
                return
            existing = row["questions"] or []
            if isinstance(existing, str):
                existing = json.loads(existing)
            if len(existing) == int(cfg["count"]):
                return

            async with self.db.pool.acquire() as c:
                rows = await c.fetch(
                    """SELECT question,options,correct_index,explanation,pyq_year,question_type,detailed_solution
                       FROM arena_question_bank
                       WHERE chapter_key=$1 AND language=$2
                       ORDER BY random() LIMIT $3""",
                    self.chapter_key(cfg["chapter"]),
                    cfg["language"],
                    cfg["count"],
                )
            questions = [self._row_question(r) for r in rows]

            missing = int(cfg["count"]) - len(questions)
            if missing > 0:
                source_context = await self._get_source_context(
                    cfg["chapter"], cfg["language"]
                )
                generated = await self._generate(
                    cfg["chapter"], cfg["language"], missing,
                    source_context=source_context,
                )
                async with self.db.pool.acquire() as c:
                    bank_hashes = await c.fetch(
                        """SELECT question,question_hash FROM arena_question_bank
                           WHERE chapter_key=$1 AND language=$2""",
                        self.chapter_key(cfg["chapter"]), cfg["language"]
                    )
                seen_hashes = {r["question_hash"] for r in bank_hashes}
                for row in bank_hashes:
                    normalized_new = re.sub(r"\s+", "", row["question"].casefold())
                    seen_hashes.add(hashlib.sha256(normalized_new.encode("utf-8")).hexdigest())
                for existing_question in questions:
                    normalized_new = re.sub(r"\s+", "", existing_question["question"].casefold())
                    normalized_old = re.sub(r"\W+", "", existing_question["question"].lower())
                    seen_hashes.add(hashlib.sha256(normalized_new.encode("utf-8")).hexdigest())
                    seen_hashes.add(hashlib.sha256(normalized_old.encode("utf-8")).hexdigest())
                unique_generated = []
                for item in generated:
                    normalized_new = re.sub(r"\s+", "", item["question"].casefold())
                    normalized_old = re.sub(r"\W+", "", item["question"].lower())
                    digests = {
                        hashlib.sha256(normalized_new.encode("utf-8")).hexdigest(),
                        hashlib.sha256(normalized_old.encode("utf-8")).hexdigest(),
                    }
                    if digests & seen_hashes:
                        log.warning(
                            "Arena skipped generated duplicate against question bank: session=%s",
                            session_id,
                        )
                        continue
                    seen_hashes.update(digests)
                    unique_generated.append(item)
                questions.extend(unique_generated)
                if unique_generated:
                    await self._save_bank(cfg["chapter"], cfg["language"], unique_generated)

            requested_count = int(cfg["count"])
            minimum_count = max(1, math.ceil(requested_count * 0.80))
            if len(questions) < minimum_count:
                raise RuntimeError(
                    f"Insufficient valid questions: {len(questions)}/{requested_count}; "
                    f"minimum required is {minimum_count} (80%)."
                )
            if len(questions) < requested_count:
                log.warning(
                    "Arena flexible mode: proceeding with %s/%s validated questions "
                    "(minimum=%s), session=%s",
                    len(questions), requested_count, minimum_count, session_id,
                )

            async with self.db.pool.acquire() as c:
                await c.execute(
                    """UPDATE arena_sessions
                       SET questions=$2::jsonb,
                           question_count=$3,
                           invite_expires_at=NOW()+INTERVAL '15 minutes'
                       WHERE id=$1 AND status='draft'""",
                    session_id,
                    json.dumps(questions, ensure_ascii=False),
                    len(questions),
                )
            if context:
                try:
                    invite_token = cfg.get("invite_token")
                    buttons = [
                        [InlineKeyboardButton("▶️ START QUIZ", callback_data="arena:start")],
                    ]
                    if invite_token:
                        buttons.append([
                            InlineKeyboardButton(
                                "👤 INVITE FRIENDS",
                                switch_inline_query=f"arena_invite_friend_{invite_token}",
                            ),
                            InlineKeyboardButton(
                                "👥 INVITE GROUPS",
                                switch_inline_query=f"arena_invite_group_{invite_token}",
                            ),
                        ])
                    await context.bot.send_message(
                        chat_id=cfg["chat_id"],
                        text=(
                            f"✅ {len(questions)} questions are ready and passed structural validation.\\n"
                            + (f"ℹ️ Requested: {requested_count}; available: {len(questions)}. Invalid items were skipped.\\n\\n" if len(questions) < requested_count else "\\n")
                            + f"📖 {cfg['chapter']}\\n"
                            + f"🆔 Session ID: {cfg.get('session_code') or session_id}\\n"
                            + "Invite friends/groups, or start the quiz."
                        ),
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
                except Exception:
                    # Notification delivery must not invalidate a successfully
                    # prepared question set.
                    log.exception("Arena questions prepared but ready notice failed")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.preparation_errors[session_id] = str(e)
            log.exception("Arena question preparation failed for %s: %s", session_id, e)
            try:
                async with self.db.pool.acquire() as c:
                    await c.execute(
                        """UPDATE arena_sessions SET status='failed',ended_at=NOW()
                           WHERE id=$1 AND status='draft'""",
                        session_id,
                    )
            except Exception:
                log.exception("Could not mark failed Arena preparation %s", session_id)
            if context:
                try:
                    await context.bot.send_message(
                        chat_id=cfg["chat_id"],
                        text="❌ Quiz questions could not be prepared. Please run /quiz again. No credits were deducted."
                    )
                except Exception:
                    log.exception("Could not send Arena preparation failure notice")
        finally:
            self.preparation_tasks.pop(session_id, None)

    async def _bank_count(self, chapter: str, language: str) -> int:
        async with self.db.pool.acquire() as c:
            return int(await c.fetchval(
                """SELECT COUNT(*) FROM arena_question_bank
                   WHERE chapter_key=$1 AND language=$2""",
                self.chapter_key(chapter), language
            ) or 0)

    async def start_session(self, user_id: int, cfg: dict, context, status_message):
        """Atomically claim the Arena slot and consume credits.

        The session status change, credit debit, ledger entry, and creator
        destination are committed in one PostgreSQL transaction. This avoids
        leaving a stuck ``ready`` session or consuming credits if setup fails.
        """
        session_id = cfg["session_id"]
        lock = self.session_locks.setdefault(session_id, asyncio.Lock())

        async with lock:
            credits_committed = False
            job_scheduled = False
            refund_succeeded = False

            try:
                async with self.db.pool.acquire() as c:
                    row = await c.fetchrow(
                        """
                        SELECT status, questions
                        FROM arena_sessions
                        WHERE id=$1 AND creator_id=$2
                        """,
                        session_id,
                        user_id,
                    )

                if not row:
                    await status_message.reply_text(
                        "❌ This quiz setup has expired. Run /quiz again."
                    )
                    return

                if row["status"] != "draft":
                    await status_message.reply_text(
                        "⏳ This quiz setup is no longer available. "
                        "Run /quiz to create a new one."
                    )
                    return

                task = self.preparation_tasks.get(session_id)
                if task and not task.done():
                    await status_message.reply_text(
                        "⚙️ Questions are still being prepared. "
                        "Wait for the confirmation message, then press Done."
                    )
                    return

                if session_id in self.preparation_errors:
                    self.preparation_errors.pop(session_id, None)
                    raise RuntimeError("QUESTION_PREPARATION_FAILED")

                questions = row["questions"] or []
                if isinstance(questions, str):
                    questions = json.loads(questions)

                requested_count = int(cfg["count"])
                actual_count = len(questions)
                minimum_count = max(1, math.ceil(requested_count * 0.80))
                if actual_count < minimum_count:
                    raise RuntimeError(
                        f"PREPARED_QUESTION_SET_INCOMPLETE: {actual_count}/{requested_count}; "
                        f"minimum={minimum_count}"
                    )
                cfg["count"] = actual_count
                cost = math.ceil(actual_count / 5)
                cfg["cost"] = cost
                metadata = {
                    "source": "ai_quiz_arena",
                    "session_id": session_id,
                    "questions": actual_count,
                    "requested_questions": requested_count,
                }

                # All database-side setup is atomic. Group locks are claimed
                # together with the credit debit and destination registration.
                async with self.db.pool.acquire() as c:
                    async with c.transaction():
                        claimed = await c.fetchval(
                            """
                            UPDATE arena_sessions
                            SET status='active'
                            WHERE id=$1 AND creator_id=$2 AND status='draft'
                            RETURNING id
                            """,
                            session_id,
                            user_id,
                        )
                        if not claimed:
                            raise RuntimeError("SESSION_NOT_DRAFT")

                        credit_row = await c.fetchrow(
                            """
                            UPDATE ai_credits
                            SET balance = balance - $2,
                                total_used = total_used + $2,
                                updated_at = NOW()
                            WHERE user_id = $1 AND balance >= $2
                            RETURNING balance
                            """,
                            user_id,
                            cost,
                        )
                        if not credit_row:
                            raise RuntimeError("INSUFFICIENT_CREDITS")

                        await c.execute(
                            """
                            INSERT INTO ai_credit_transactions(
                                user_id, amount, transaction_type,
                                balance_after, metadata
                            )
                            VALUES($1,$2,$3,$4,$5::jsonb)
                            """,
                            user_id,
                            -cost,
                            "ARENA_QUIZ_CREATE",
                            credit_row["balance"],
                            json.dumps(metadata),
                        )

                        await c.execute(
                            """
                            INSERT INTO arena_destinations(
                                session_id, chat_id, chat_type, title, username
                            )
                            VALUES($1,$2,$3,$4,$5)
                            ON CONFLICT(session_id, chat_id) DO UPDATE
                            SET status='joined', username=EXCLUDED.username
                            """,
                            session_id,
                            cfg["chat_id"],
                            cfg["chat_type"],
                            cfg["title"],
                            cfg.get("username"),
                        )
                        await c.execute(
                            """INSERT INTO arena_waiting_members(session_id,user_id,chat_id)
                               VALUES($1,$2,$3) ON CONFLICT(session_id,user_id) DO NOTHING""",
                            session_id, user_id, cfg["chat_id"],
                        )
                        group_ids = await c.fetch(
                            """SELECT chat_id FROM arena_destinations
                               WHERE session_id=$1 AND status='joined'
                                 AND chat_type IN ('group','supergroup')
                               ORDER BY chat_id""",
                            session_id,
                        )
                        for group_row in group_ids:
                            group_id = group_row["chat_id"]
                            existing_lock = await c.fetchrow(
                                """SELECT l.session_id,s.status
                                   FROM arena_group_locks l
                                   LEFT JOIN arena_sessions s ON s.id=l.session_id
                                   WHERE l.group_id=$1 FOR UPDATE OF l""",
                                group_id,
                            )
                            if existing_lock and existing_lock["session_id"] != session_id:
                                if existing_lock["status"] not in ("finished", "cancelled", "failed", "expired"):
                                    raise RuntimeError("GROUP_BUSY")
                                await c.execute(
                                    "DELETE FROM arena_group_locks WHERE group_id=$1",
                                    group_id,
                                )
                            acquired = await c.fetchval(
                                """INSERT INTO arena_group_locks(group_id,session_id)
                                   VALUES($1,$2) ON CONFLICT(group_id) DO UPDATE
                                   SET session_id=EXCLUDED.session_id,acquired_at=NOW()
                                   WHERE arena_group_locks.session_id=EXCLUDED.session_id
                                   RETURNING group_id""",
                                group_id, session_id
                            )
                            if not acquired:
                                raise RuntimeError("GROUP_BUSY")

                credits_committed = True

                if not context.job_queue:
                    raise RuntimeError("JOB_QUEUE_UNAVAILABLE")

                context.job_queue.run_once(
                    self._tick,
                    when=3,
                    data={"session_id": session_id},
                    name=f"arena:{session_id}",
                )
                job_scheduled = True

                self.configs.pop(user_id, None)
                try:
                    await status_message.reply_text(
                        f"✅ Quiz ready! {actual_count} questions prepared. "
                        + (f"(requested {requested_count}; invalid questions skipped)\n" if actual_count < requested_count else "")
                        + f"Credits used: {cost}. Starting in 3 seconds."
                    )
                except Exception:
                    # The scheduled quiz must continue even if the status
                    # notification cannot be delivered.
                    log.exception(
                        "Arena %s started but status message delivery failed",
                        session_id,
                    )

            except Exception as e:
                log.exception(
                    "Arena session start failed (session_id=%s, user_id=%s): %s",
                    session_id,
                    user_id,
                    e,
                )

                # If the DB transaction committed but scheduling failed,
                # refund the debit and record the refund in the same transaction.
                if credits_committed and not job_scheduled:
                    try:
                        async with self.db.pool.acquire() as c:
                            async with c.transaction():
                                refund_row = await c.fetchrow(
                                    """
                                    UPDATE ai_credits
                                    SET balance = balance + $2,
                                        total_used = GREATEST(total_used - $2, 0),
                                        updated_at = NOW()
                                    WHERE user_id=$1
                                    RETURNING balance
                                    """,
                                    user_id,
                                    int(cfg["cost"]),
                                )
                                if refund_row:
                                    await c.execute(
                                        """
                                        INSERT INTO ai_credit_transactions(
                                            user_id, amount, transaction_type,
                                            balance_after, metadata
                                        )
                                        VALUES($1,$2,$3,$4,$5::jsonb)
                                        """,
                                        user_id,
                                        int(cfg["cost"]),
                                        "ARENA_QUIZ_CREATE_REFUND",
                                        refund_row["balance"],
                                        json.dumps({
                                            "source": "ai_quiz_arena",
                                            "session_id": session_id,
                                            "reason": str(e)[:300],
                                        }),
                                    )
                        refund_succeeded = bool(refund_row)
                    except Exception:
                        log.exception(
                            "CRITICAL: Arena credit refund failed for session %s",
                            session_id,
                        )

                # Release this session's group locks if setup or scheduling fails.
                try:
                    async with self.db.pool.acquire() as c:
                        await c.execute(
                            """
                            UPDATE arena_sessions
                            SET status='failed', ended_at=NOW()
                            WHERE id=$1
                              AND status IN ('draft','generating','ready','active')
                            """,
                            session_id,
                        )
                        await c.execute(
                            "DELETE FROM arena_group_locks WHERE session_id=$1",
                            session_id,
                        )
                except Exception:
                    log.exception(
                        "Could not mark failed Arena session %s",
                        session_id,
                    )

                self.configs.pop(user_id, None)
                self.preparation_errors.pop(session_id, None)

                error_code = str(e)
                if error_code == "GROUP_BUSY":
                    message = (
                        "⏳ This group already has an active AI Quiz Arena session. "
                        "Wait until it finishes or the creator stops it."
                    )
                elif error_code == "INSUFFICIENT_CREDITS":
                    message = (
                        "❌ Your available credits changed before the quiz started. "
                        "No credits were deducted. Check /credits and try again."
                    )
                elif error_code == "QUESTION_PREPARATION_FAILED":
                    message = (
                        "❌ Question preparation failed. No credits were deducted. "
                        "Please run /quiz again. Check Render logs for the preparation error."
                    )
                elif error_code in (
                    "PREPARED_QUESTION_SET_INCOMPLETE",
                    "SESSION_NOT_DRAFT",
                ):
                    message = (
                        "❌ The prepared quiz session is incomplete or expired. "
                        "No credits were deducted. Please run /quiz again."
                    )
                elif credits_committed and not refund_succeeded:
                    message = (
                        "⚠️ Quiz setup failed after credit processing. "
                        "Please check /credits before retrying and share the "
                        "Arena session-start traceback from Render logs."
                    )
                else:
                    message = (
                        "❌ Quiz setup failed. No credits were deducted. "
                        "Please run /quiz again. If it repeats, share the "
                        "Arena session-start traceback from Render logs."
                    )

                try:
                    await status_message.reply_text(message)
                except Exception:
                    log.exception(
                        "Could not send Arena setup failure message for %s",
                        session_id,
                    )

    async def _get_source_context(self, chapter: str, language: str) -> str:
        """Retrieve any curated NCERT/syllabus/PYQ context stored for this chapter."""
        async with self.db.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT source_type,source_title,source_text
                   FROM arena_chapter_sources
                   WHERE chapter_key=$1 AND language IN ($2,'all')
                   ORDER BY CASE source_type
                       WHEN 'ncert' THEN 1
                       WHEN 'neet_syllabus' THEN 2
                       WHEN 'pyq_pattern' THEN 3
                       ELSE 4 END,
                       updated_at DESC
                   LIMIT 12""",
                self.chapter_key(chapter), language,
            )
        blocks = []
        remaining = 24000
        for row in rows:
            block = (
                f"[{row['source_type'].upper()} | {row['source_title']}]\\n"
                f"{row['source_text']}"
            )
            block = block[:remaining]
            if block:
                blocks.append(block)
                remaining -= len(block)
            if remaining <= 0:
                break
        return "\\n\\n".join(blocks)

    async def _generate(self, chapter: str, language: str, count: int, source_context: str = "") -> list[dict]:
        if not self.provider:
            raise RuntimeError("Gemini API is not configured. Set GEMINI_API_KEY.")
        lang = "Hindi" if language == "hindi" else "English"
        source_block = (
            "CURATED SOURCE CONTEXT (use as primary grounding; do not contradict it):\n"
            + source_context
            if source_context else
            "No curated NCERT/latest-syllabus/PYQ source text is stored for this chapter. Use conservative established knowledge, avoid uncertain/out-of-syllabus claims, and do not claim exact PYQ provenance.\n"
        )
        prompt = f"""Create exactly {count} distinct NEET-UG single-correct MCQs for the NCERT chapter: {chapter}. Language: {lang}.
{source_block}
Use the combined study scope: NCERT concepts, the latest NEET-UG syllabus boundaries, and NEET previous-year question (PYQ) patterns. Include NEET-style objective formats such as assertion-reason and statement-based questions, but convert every item into exactly four options with exactly one correct option.
Do not claim an item is an actual PYQ unless its exact year is independently verified from supplied source material. If not verified, set pyq_year to null. Never invent a PYQ year, citation, fact, or out-of-syllabus content.
Avoid duplicates and near-duplicates. Check the exact answer and provide a concise explanation.
Return ONLY a valid JSON array. Every item must contain: question, options (exactly 4 distinct strings, each <=100 characters), correct_index (integer 0-3, never a string), explanation (1-180 characters), detailed_solution (1-3500 characters), pyq_year (integer or null), question_type (single_correct, assertion_reason, or statement_based).
The question must be <=280 characters BEFORE the required attribution. Append the literal text "【@DrQuizRobot】" at the end of every question. Do not use markdown fences."""
        raw = await self.provider.generate(
            [ChatMessage(role="user", content=prompt)],
            "You are a careful NEET-UG question writer. Accuracy is more important than speed. Return valid JSON matching every field and length limit.",
            max_output_tokens=8192,
            timeout_seconds=120,
        )
        try:
            valid, errors = self._parse_generated(raw, count, allow_partial=True)
        except (ValueError, TypeError, json.JSONDecodeError) as first_error:
            valid, errors = [], [f"response_parse_error: {str(first_error)[:250]}"]

        missing = count - len(valid)
        if missing > 0:
            repair_prompt = (
                f"Generate {missing} NEW valid NEET MCQs as a JSON array. Do not repeat any question in the original response. "
                "Each object must have question, options (exactly four distinct strings <=100 chars), correct_index "
                "(integer 0-3), explanation (1-180 chars), detailed_solution (1-3500 chars), pyq_year (null unless verified), "
                "and question_type (single_correct/assertion_reason/statement_based). Question <=280 chars before appending "
                "【@DrQuizRobot】. Return JSON only. Preserve NCERT/syllabus accuracy. "
                f"Validation issues in first response: {errors[:12]}.\n"
                f"Already valid questions (do not repeat): {json.dumps([q['question'] for q in valid], ensure_ascii=False)}\n"
                f"Source context:\n{source_context[:10000]}\nOriginal response:\n{str(raw)[:18000]}"
            )
            try:
                repaired = await self.provider.generate(
                    [ChatMessage(role="user", content=repair_prompt)],
                    "Generate only structurally valid, accurate NEET MCQs in JSON. Do not invent PYQ provenance.",
                    max_output_tokens=8192,
                    timeout_seconds=120,
                )
                repaired_valid, repair_errors = self._parse_generated(repaired, missing, allow_partial=True)
                seen = {re.sub(r"\s+", "", q["question"].casefold()) for q in valid}
                for item in repaired_valid:
                    key = re.sub(r"\s+", "", item["question"].casefold())
                    if key not in seen and len(valid) < count:
                        valid.append(item)
                        seen.add(key)
                errors.extend(repair_errors)
            except Exception as repair_error:
                errors.append(f"repair_failed: {str(repair_error)[:250]}")

        if errors:
            log.warning(
                "Arena generation validation: requested=%s valid=%s skipped_or_repair_issues=%s",
                count, len(valid), errors[:15],
            )
        if not valid:
            raise ValueError("Gemini returned no structurally valid questions")
        return valid[:count]

    @staticmethod
    def _parse_generated(raw: str, count: int, allow_partial: bool = False):
        raw = str(raw or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("AI output was not a JSON array")
        if not allow_partial and len(data) != count:
            raise ValueError("AI output did not contain the exact requested question count")

        out, seen, errors = [], set(), []
        for position, item in enumerate(data, start=1):
            try:
                if not isinstance(item, dict):
                    raise ValueError("not_a_json_object")
                q = str(item.get("question", "")).strip()
                opts = item.get("options")
                idx = item.get("correct_index")
                explanation = str(item.get("explanation", "")).strip()
                detailed_solution = str(item.get("detailed_solution") or explanation).strip()
                pyq_year = None
                question_type = str(item.get("question_type") or "single_correct").strip().lower()
                if question_type not in ("single_correct", "assertion_reason", "statement_based"):
                    question_type = "single_correct"
                if not q:
                    raise ValueError("empty_question")
                if not q.endswith("【@DrQuizRobot】"):
                    q = q.rstrip() + " 【@DrQuizRobot】"
                if len(q) > 300:
                    raise ValueError(f"question_too_long:{len(q)}")
                if not isinstance(opts, list) or len(opts) != 4:
                    raise ValueError("options_count_not_4")
                if any(not isinstance(x, str) or not x.strip() for x in opts):
                    raise ValueError("empty_or_non_string_option")
                if len({re.sub(r"\s+", "", x.casefold()) for x in opts}) != 4:
                    raise ValueError("duplicate_options")
                if any(len(x.strip()) > 100 for x in opts):
                    raise ValueError("option_too_long")
                if not isinstance(idx, int) or isinstance(idx, bool) or idx not in range(4):
                    raise ValueError("invalid_correct_index")
                if not explanation:
                    raise ValueError("empty_explanation")
                if len(explanation) > 180:
                    raise ValueError(f"explanation_too_long:{len(explanation)}")
                if not detailed_solution:
                    raise ValueError("empty_detailed_solution")
                if len(detailed_solution) > 3500:
                    raise ValueError(f"detailed_solution_too_long:{len(detailed_solution)}")
                norm = re.sub(r"\s+", "", q.casefold())
                if norm in seen:
                    raise ValueError("duplicate_question")
                seen.add(norm)
                out.append({
                    "question": q,
                    "options": [x.strip() for x in opts],
                    "correct_index": idx,
                    "explanation": explanation,
                    "detailed_solution": detailed_solution,
                    "pyq_year": pyq_year,
                    "question_type": question_type,
                })
                if len(out) >= count:
                    break
            except (ValueError, TypeError, AttributeError) as item_error:
                errors.append(f"item_{position}:{str(item_error)[:100]}")
        if not allow_partial and len(out) != count:
            raise ValueError(f"Only {len(out)}/{count} valid questions")
        return out, errors

    @staticmethod
    def _row_question(r):
        options = r["options"]
        # asyncpg returns JSON/JSONB as a JSON string unless a custom codec
        # is configured. Telegram send_poll requires a Python list.
        if isinstance(options, str):
            options = json.loads(options)
        if not isinstance(options, list):
            raise ValueError("Question bank options are not a valid JSON array")
        return {
            "question": r["question"],
            "options": options,
            "correct_index": int(r["correct_index"]),
            "explanation": r["explanation"],
            "detailed_solution": r["detailed_solution"] or r["explanation"],
            "pyq_year": r["pyq_year"],
            "question_type": r["question_type"],
        }

    async def _save_bank(self, chapter, language, questions):

        key = self.chapter_key(chapter)

        async with self.db.pool.acquire() as c:

            async with c.transaction():

                # Lock this chapter-language bank.
                await c.execute(
                    """
                    SELECT pg_advisory_xact_lock(
                        hashtextextended($1, 0)
                    )
                    """,
                    f"{key}:{language}"
                )

                current = await c.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM arena_question_bank
                    WHERE chapter_key=$1
                    AND language=$2
                    """,
                    key,
                    language
                )

                for item in questions:

                    if current >= 1000:
                        break

                    normalized = re.sub(
                        r"\W+",
                        "",
                        item["question"].lower()
                    )

                    h = hashlib.sha256(
                        normalized.encode("utf-8")
                    ).hexdigest()

                    result = await c.execute(
                        """
                        INSERT INTO arena_question_bank(
                            chapter_key,
                            chapter,
                            language,
                            question,
                            options,
                            correct_index,
                            explanation,
                            question_hash,
                            pyq_year,
                            question_type,
                            detailed_solution
                        )
                        VALUES(
                            $1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,$11
                        )
                        ON CONFLICT(
                            chapter_key,
                            language,
                            question_hash
                        )
                        DO NOTHING
                        """,
                        key,
                        chapter,
                        language,
                        item["question"],
                        json.dumps(
                            item["options"],
                            ensure_ascii=False
                        ),
                        item["correct_index"],
                        item["explanation"],
                        h,
                        item.get("pyq_year"),
                        item.get("question_type", "single_correct"),
                        item.get("detailed_solution") or item["explanation"]
                    )

                    if result.endswith("1"):
                        current += 1

    async def inline_query(self, update, context):
        query = update.inline_query.query.strip()
        if not query.startswith(("arena_invite_", "arena_invite_friend_", "arena_invite_group_")):
            return False
        mode = "any"
        if query.startswith("arena_invite_friend_"):
            mode = "friend"
            token = query.removeprefix("arena_invite_friend_")
        elif query.startswith("arena_invite_group_"):
            mode = "group"
            token = query.removeprefix("arena_invite_group_")
        else:
            token = query.removeprefix("arena_invite_")
        async with self.db.pool.acquire() as c:
            row = await c.fetchrow("""SELECT i.session_id,s.chapter,s.language,s.question_count,s.seconds,s.status,s.session_code,s.invite_expires_at FROM arena_invites i JOIN arena_sessions s ON s.id=i.session_id WHERE i.token=$1""", token)
        if not row or row["status"] not in ("draft", "generating", "ready") or (row["invite_expires_at"] and row["invite_expires_at"] <= datetime_now_utc()):
            await update.inline_query.answer([], cache_time=0, is_personal=True)
            return True
        text = (
            f"📨 NEET QUIZ INVITATION\\n\\n"
            f"📖 Chapter: {row['chapter']}\\n"
            f"🆔 Session ID: {row['session_code'] or row['session_id']}\\n"
            f"🌐 Language: {row['language'].title()}\\n"
            f"❓ Questions: {row['question_count']}\\n"
            f"⏱ Time per question: {row['seconds']} sec\\n\\n"
            f"━━━━━━━━━━━━━━━━━━\\n"
            f"To accept: tap ACCEPT, then send the Session ID in the destination chat.\\n"
            f"👥 Group admin: send `/accept {row['session_code'] or row['session_id']}` in the group. Members can send the ID individually to join the waiting room.\\n"
            f"👤 Private: recipient must start the bot, then send `/accept {row['session_code'] or row['session_id']}` in the bot's private chat.\\n\\n"
            f"Invitation expires 15 minutes after the quiz is ready."
        )
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ ACCEPT",
                    callback_data=f"arena:accept:{row['session_id']}"
                ),
                InlineKeyboardButton(
                    "❌ REJECT",
                    callback_data=f"arena:reject:{row['session_id']}"
                )
            ]
        ])
        result = InlineQueryResultArticle(id="arena_"+token, title="📨 Invite to NEET Quiz", description=f"{row['chapter']} · {row['question_count']} questions", input_message_content=InputTextMessageContent(text), reply_markup=markup)
        await update.inline_query.answer([result], cache_time=0, is_personal=True)
        return True

    async def _tick(self, context):
        sid = context.job.data["session_id"]
        lock = self.session_locks.setdefault(sid, asyncio.Lock())
        async with lock:
            finish_now = False
            no_destinations = False
            async with self.db.pool.acquire() as c:
                session = await c.fetchrow("SELECT * FROM arena_sessions WHERE id=$1", sid)
                if not session or session["status"] not in ("active", "ready"):
                    return
                next_index = int(session["current_index"]) + 1
                questions = session["questions"]
                if isinstance(questions, str):
                    questions = json.loads(questions)
                if next_index >= len(questions):
                    await c.execute(
                        "UPDATE arena_sessions SET status='finished',ended_at=NOW() WHERE id=$1 AND status IN ('active','ready')",
                        sid,
                    )
                    await c.execute("DELETE FROM arena_group_locks WHERE session_id=$1", sid)
                    finish_now = True
                else:
                    destinations = await c.fetch(
                        "SELECT * FROM arena_destinations WHERE session_id=$1 AND status='joined'",
                        sid,
                    )
                    if not destinations:
                        await c.execute(
                            "UPDATE arena_sessions SET status='failed',ended_at=NOW() WHERE id=$1",
                            sid,
                        )
                        await c.execute("DELETE FROM arena_group_locks WHERE session_id=$1", sid)
                        no_destinations = True
                    else:
                        await c.execute(
                            """UPDATE arena_sessions
                               SET status='active',current_index=$2,
                                   started_at=COALESCE(started_at,NOW()),
                                   question_started_at=NOW()
                               WHERE id=$1""",
                            sid, next_index,
                        )

            if finish_now:
                await self._leaderboard(context, sid)
                return
            if no_destinations:
                return

            qdata = questions[next_index]
            semaphore = asyncio.Semaphore(10)

            async def deliver_poll(dest):
                async with semaphore:
                    try:
                        poll = await context.bot.send_poll(
                            chat_id=dest["chat_id"],
                            question=qdata["question"],
                            options=qdata["options"],
                            type="quiz",
                            correct_option_id=int(qdata["correct_index"]),
                            is_anonymous=False,
                            open_period=int(session["seconds"]),
                            explanation=(qdata.get("explanation") or "")[:180],
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton(
                                    "📘 Detailed Solution",
                                    callback_data=f"arena:solution:{sid}:{next_index}",
                                )
                            ]]),
                        )
                        self.polls[poll.poll.id] = {
                            "session_id": sid,
                            "chat_id": dest["chat_id"],
                            "question_index": next_index,
                            "correct_index": int(qdata["correct_index"]),
                        }
                        async with self.db.pool.acquire() as c:
                            await c.execute(
                                """INSERT INTO arena_poll_map
                                   (poll_id,session_id,chat_id,question_index,correct_index)
                                   VALUES($1,$2,$3,$4,$5) ON CONFLICT(poll_id) DO NOTHING""",
                                poll.poll.id, sid, dest["chat_id"], next_index,
                                int(qdata["correct_index"])
                            )
                    except Exception as e:
                        log.warning("Arena poll delivery failed chat=%s: %s", dest["chat_id"], e)
                        async with self.db.pool.acquire() as c:
                            await c.execute(
                                """UPDATE arena_destinations SET status='failed'
                                   WHERE session_id=$1 AND chat_id=$2""",
                                sid, dest["chat_id"]
                            )
                            await c.execute(
                                "DELETE FROM arena_group_locks WHERE session_id=$1 AND group_id=$2",
                                sid, dest["chat_id"]
                            )

            await asyncio.gather(*(deliver_poll(dest) for dest in destinations))
            async with self.db.pool.acquire() as c:
                remaining = int(await c.fetchval(
                    "SELECT COUNT(*) FROM arena_destinations WHERE session_id=$1 AND status='joined'",
                    sid,
                ) or 0)
                if remaining == 0:
                    await c.execute(
                        "UPDATE arena_sessions SET status='failed',ended_at=NOW() WHERE id=$1 AND status='active'",
                        sid,
                    )
                    await c.execute("DELETE FROM arena_group_locks WHERE session_id=$1", sid)
                    return
            context.job_queue.run_once(
                self._tick, when=int(session["seconds"]),
                data={"session_id": sid}, name=f"arena:{sid}"
            )

    async def poll_answer(self, update, context) -> bool:
        pa = update.poll_answer
        info = self.polls.get(pa.poll_id)
        if not info:
            async with self.db.pool.acquire() as c:
                row = await c.fetchrow("SELECT session_id,chat_id,question_index,correct_index FROM arena_poll_map WHERE poll_id=$1", pa.poll_id)
            if row:
                info = {"session_id":row["session_id"],"chat_id":row["chat_id"],"question_index":row["question_index"],"correct_index":row["correct_index"]}
                self.polls[pa.poll_id] = info
        if not info: return False
        user = pa.user
        selected = pa.option_ids[0] if pa.option_ids else -1
        # A participant is counted only after selecting an actual answer in at least one poll.
        if selected < 0:
            return True
        correct = selected == info["correct_index"]
        points = 4 if correct else -1
        await self.db.add_user(user.id, user.username, user.first_name, user.last_name)
        async with self.db.pool.acquire() as c:
            async with c.transaction():
                is_waiting = await c.fetchval(
                    """SELECT EXISTS(
                         SELECT 1 FROM arena_waiting_members
                         WHERE session_id=$1 AND user_id=$2 AND chat_id=$3
                       )""",
                    info["session_id"], user.id, info["chat_id"],
                )
                if not is_waiting:
                    return True
                await c.execute("INSERT INTO arena_participants(session_id,user_id,chat_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", info["session_id"], user.id, info["chat_id"])
                participant_chat = await c.fetchval("SELECT chat_id FROM arena_participants WHERE session_id=$1 AND user_id=$2", info["session_id"], user.id)
                # A participant is locked to the first group/private chat in which they answer.
                if participant_chat != info["chat_id"]:
                    return True
                await c.execute("""INSERT INTO arena_answers(session_id,chat_id,user_id,username,first_name,last_name,question_index,selected_index,is_correct,points) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(session_id,user_id,question_index) DO UPDATE SET selected_index=EXCLUDED.selected_index,is_correct=EXCLUDED.is_correct,points=EXCLUDED.points,answered_at=NOW()""", info["session_id"], info["chat_id"], user.id, user.username, user.first_name, user.last_name, info["question_index"], selected, correct, points)
        return True

    async def _register_destination(self, c, session_id, chat_id, chat_type, title, username=None, user_id=None):
        """Atomically register an invited destination within session limits."""
        async with c.transaction():
            session = await c.fetchrow(
                """SELECT status,session_code,invite_expires_at,
                          creator_chat_id,creator_chat_type
                   FROM arena_sessions WHERE id=$1 FOR UPDATE""",
                session_id,
            )
            if not session or session["status"] not in ("draft", "generating", "ready"):
                raise ValueError("INVITATION_CLOSED")
            if session["invite_expires_at"] and session["invite_expires_at"] <= datetime_now_utc():
                raise ValueError("INVITATION_EXPIRED")

            existing = await c.fetchrow(
                "SELECT status FROM arena_destinations WHERE session_id=$1 AND chat_id=$2",
                session_id, chat_id,
            )
            if existing and existing["status"] == "joined":
                if user_id is not None:
                    await c.execute(
                        """INSERT INTO arena_waiting_members(session_id,user_id,chat_id)
                           VALUES($1,$2,$3) ON CONFLICT(session_id,user_id) DO NOTHING""",
                        session_id, user_id, chat_id,
                    )
                return session["session_code"] or session_id

            is_new_destination = not existing or existing["status"] != "joined"
            is_group = chat_type in (ChatType.GROUP, ChatType.SUPERGROUP)
            if is_group:
                group_lock = await c.fetchrow(
                    """SELECT l.session_id,s.status FROM arena_group_locks l
                       LEFT JOIN arena_sessions s ON s.id=l.session_id
                       WHERE l.group_id=$1 FOR UPDATE OF l""",
                    chat_id,
                )
                if group_lock and group_lock["session_id"] != session_id:
                    if group_lock["status"] not in ("finished", "cancelled", "failed", "expired"):
                        raise ValueError("GROUP_BUSY")
                    await c.execute("DELETE FROM arena_group_locks WHERE group_id=$1", chat_id)

                count = await c.fetchval(
                    """SELECT COUNT(*) FROM arena_destinations
                       WHERE session_id=$1 AND status='joined'
                         AND chat_type IN ('group','supergroup')""",
                    session_id,
                )
                creator_group_reserved = (
                    session["creator_chat_type"] in (ChatType.GROUP, ChatType.SUPERGROUP)
                    and int(session["creator_chat_id"] or 0) != int(chat_id)
                    and not await c.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM arena_destinations WHERE session_id=$1 AND chat_id=$2 AND status='joined')",
                        session_id, session["creator_chat_id"]
                    )
                )
                if is_new_destination and int(count or 0) + int(bool(creator_group_reserved)) >= 5:
                    raise ValueError("GROUP_LIMIT")
            else:
                count = await c.fetchval(
                    """SELECT COUNT(*) FROM arena_destinations
                       WHERE session_id=$1 AND status='joined'
                         AND chat_type='private'""",
                    session_id,
                )
                creator_private_reserved = (
                    session["creator_chat_type"] == ChatType.PRIVATE
                    and int(session["creator_chat_id"] or 0) != int(chat_id)
                    and not await c.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM arena_destinations WHERE session_id=$1 AND chat_id=$2 AND status='joined')",
                        session_id, session["creator_chat_id"]
                    )
                )
                if is_new_destination and int(count or 0) + int(bool(creator_private_reserved)) >= 10:
                    raise ValueError("PRIVATE_LIMIT")

            await c.execute(
                """INSERT INTO arena_destinations(
                       session_id,chat_id,chat_type,title,status,username
                   ) VALUES($1,$2,$3,$4,'joined',$5)
                   ON CONFLICT(session_id,chat_id) DO UPDATE
                   SET status='joined',title=EXCLUDED.title,username=EXCLUDED.username""",
                session_id, chat_id, chat_type, title, username,
            )
            await c.execute(
                """INSERT INTO arena_invite_responses(session_id,chat_id,response)
                   VALUES($1,$2,'accepted')
                   ON CONFLICT(session_id,chat_id) DO UPDATE
                   SET response='accepted',updated_at=NOW()""",
                session_id, chat_id,
            )
            if user_id is not None:
                await c.execute(
                    """INSERT INTO arena_waiting_members(session_id,user_id,chat_id)
                       VALUES($1,$2,$3) ON CONFLICT(session_id,user_id) DO NOTHING""",
                    session_id, user_id, chat_id,
                )
            return session["session_code"] or session_id

    async def session_code_message(self, update, context):
        """Register a destination or a group member from a plain Session ID."""
        message = update.effective_message
        user, chat = update.effective_user, update.effective_chat
        if not message or not user or not chat or not message.text:
            return
        code = message.text.strip().upper()
        if not re.fullmatch(r"NQ-[A-Z0-9]{1,8}-[0-9]{8}", code):
            return
        try:
            is_group = chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
            is_group_admin = False
            if is_group:
                try:
                    member = await context.bot.get_chat_member(chat.id, user.id)
                    is_group_admin = member.status in ("administrator", "creator")
                except Exception:
                    await message.reply_text("Unable to verify group permissions.")
                    return

            async with self.db.pool.acquire() as c:
                session_id = await c.fetchval(
                    """SELECT id FROM arena_sessions
                       WHERE session_code=$1 AND status IN ('draft','generating','ready')
                       LIMIT 1""",
                    code,
                )
                if not session_id:
                    raise ValueError("INVITATION_CLOSED")

                individual_join = False
                if is_group and not is_group_admin:
                    registered = await c.fetchval(
                        """SELECT EXISTS(
                             SELECT 1 FROM arena_destinations
                             WHERE session_id=$1 AND chat_id=$2 AND status='joined'
                           )""",
                        session_id, chat.id,
                    )
                    if not registered:
                        await message.reply_text("Your group has not accepted this invitation yet. Ask a group admin to send the Session ID.")
                        return
                    await c.execute(
                        """INSERT INTO arena_waiting_members(session_id,user_id,chat_id)
                           VALUES($1,$2,$3) ON CONFLICT(session_id,user_id) DO NOTHING""",
                        session_id, user.id, chat.id,
                    )
                    display_code = code
                    individual_join = True
                else:
                    display_code = await self._register_destination(
                        c, session_id, chat.id, chat.type,
                        chat.title or user.first_name or "Private",
                        getattr(chat, "username", None), user.id,
                    )
                    await c.execute(
                        """INSERT INTO arena_waiting_members(session_id,user_id,chat_id)
                           VALUES($1,$2,$3) ON CONFLICT(session_id,user_id) DO NOTHING""",
                        session_id, user.id, chat.id,
                    )

            if individual_join:
                await message.reply_text(
                    f"✅ You are in the waiting room for this group quiz.\\n"
                    f"🆔 Session ID: {display_code}\\n"
                    "You count as a participant after answering at least one quiz question."
                )
            else:
                await message.reply_text(
                    f"✅ Invitation accepted. This chat is registered.\\n🆔 Session ID: {display_code}"
                )
        except ValueError as e:
            messages = {
                "INVITATION_CLOSED": "This Session ID is invalid, expired, or no longer accepting destinations.",
                "INVITATION_EXPIRED": "This invitation has expired (15-minute limit).",
                "GROUP_BUSY": "This group already has another active AI Quiz Arena session.",
                "GROUP_LIMIT": "This session has reached its maximum of 5 groups.",
                "PRIVATE_LIMIT": "This session has reached its maximum of 10 private chats.",
            }
            await message.reply_text("❌ " + messages.get(str(e), "Unable to accept this invitation."))
        except Exception:
            log.exception("Arena Session ID registration failed")
            await message.reply_text("❌ Could not register this chat. Please try again.")

    async def accept_command(self, update, context):
        user, chat = update.effective_user, update.effective_chat
        if not user or not chat or not context.args:
            await update.effective_message.reply_text("Usage: /accept SESSION_ID")
            return
        session_code = context.args[0].strip().upper()
        is_group = chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
        is_group_admin = False
        if is_group:
            try:
                member = await context.bot.get_chat_member(chat.id, user.id)
                is_group_admin = member.status in ("administrator", "creator")
            except Exception:
                await update.effective_message.reply_text("Unable to verify group permissions.")
                return
        try:
            async with self.db.pool.acquire() as c:
                session_id = await c.fetchval(
                    """SELECT id FROM arena_sessions
                       WHERE (session_code=$1 OR id=$1)
                         AND status IN ('draft','generating','ready')
                         AND (invite_expires_at IS NULL OR invite_expires_at > NOW())
                       LIMIT 1""",
                    session_code,
                )
                if not session_id:
                    raise ValueError("INVITATION_CLOSED")
                if is_group and not is_group_admin:
                    registered = await c.fetchval(
                        """SELECT EXISTS(
                             SELECT 1 FROM arena_destinations
                             WHERE session_id=$1 AND chat_id=$2 AND status='joined'
                           )""",
                        session_id, chat.id,
                    )
                    if not registered:
                        await update.effective_message.reply_text("Your group has not accepted this invitation yet. Ask a group admin to send /accept with the Session ID.")
                        return
                    await c.execute(
                        """INSERT INTO arena_waiting_members(session_id,user_id,chat_id)
                           VALUES($1,$2,$3) ON CONFLICT(session_id,user_id) DO NOTHING""",
                        session_id, user.id, chat.id,
                    )
                    display_code = session_code
                    individual_join = True
                else:
                    display_code = await self._register_destination(
                        c, session_id, chat.id, chat.type,
                        chat.title or user.first_name or "Private",
                        getattr(chat, "username", None), user.id,
                    )
                    individual_join = False
            if individual_join:
                await update.effective_message.reply_text(
                    f"✅ You are in the waiting room.\\n🆔 Session ID: {display_code}\\n"
                    "You count as a participant after answering at least one quiz question."
                )
            else:
                await update.effective_message.reply_text(
                    f"✅ Invitation accepted. This chat is registered.\\n🆔 Session ID: {display_code}"
                )
        except ValueError as e:
            messages = {
                "INVITATION_CLOSED": "This invitation is invalid, expired, or no longer accepting destinations.",
                "INVITATION_EXPIRED": "This invitation has expired (15-minute limit).",
                "GROUP_BUSY": "This group already has another active AI Quiz Arena session.",
                "GROUP_LIMIT": "This session has reached its maximum of 5 groups.",
                "PRIVATE_LIMIT": "This session has reached its maximum of 10 private chats.",
            }
            await update.effective_message.reply_text("❌ " + messages.get(str(e), "Unable to accept this invitation."))
        except Exception:
            log.exception("Arena invitation acceptance failed")
            await update.effective_message.reply_text("❌ Invitation acceptance failed. Please try again.")

    async def reject_command(self, update, context):
        user, chat = update.effective_user, update.effective_chat
        if not user or not chat or not context.args:
            await update.effective_message.reply_text("Usage: /reject SESSION_ID")
            return
        code = context.args[0].strip()
        is_group = chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
        is_admin = False
        if is_group:
            try:
                member = await context.bot.get_chat_member(chat.id, user.id)
                is_admin = member.status in ("administrator", "creator")
            except Exception:
                await update.effective_message.reply_text("Unable to verify group permissions.")
                return
        async with self.db.pool.acquire() as c:
            row = await c.fetchrow(
                """SELECT id FROM arena_sessions
                   WHERE (session_code=$1 OR id=$1)
                     AND status IN ('draft','generating','ready')""",
                code,
            )
            if not row:
                await update.effective_message.reply_text("This invitation is invalid or already closed.")
                return
            sid = row["id"]
            if is_group and not is_admin:
                await c.execute(
                    "DELETE FROM arena_waiting_members WHERE session_id=$1 AND user_id=$2 AND chat_id=$3",
                    sid, user.id, chat.id,
                )
                await update.effective_message.reply_text("You have left this quiz waiting room.")
                return
            await c.execute(
                """UPDATE arena_destinations SET status='rejected'
                   WHERE session_id=$1 AND chat_id=$2""",
                sid, chat.id,
            )
            await c.execute(
                "DELETE FROM arena_waiting_members WHERE session_id=$1 AND chat_id=$2",
                sid, chat.id,
            )
            await c.execute(
                """INSERT INTO arena_invite_responses(session_id,chat_id,response)
                   VALUES($1,$2,'rejected')
                   ON CONFLICT(session_id,chat_id) DO UPDATE
                   SET response='rejected',updated_at=NOW()""",
                sid, chat.id,
            )
            await c.execute(
                "DELETE FROM arena_group_locks WHERE session_id=$1 AND group_id=$2",
                sid, chat.id,
            )
        await update.effective_message.reply_text("❌ Invitation rejected. This chat will not join the quiz.")

    async def quizstatus_command(self, update, context):
        user = update.effective_user
        if not user:
            return
        reply_markup = None
        async with self.db.pool.acquire() as c:
            row = await c.fetchrow(
                """SELECT id,session_code,chapter,question_count,status,created_at,
                          invite_expires_at,current_index,creator_chat_id,
                          creator_chat_type,questions
                   FROM arena_sessions
                   WHERE creator_id=$1
                     AND status IN ('draft','generating','ready','active')
                   ORDER BY created_at DESC LIMIT 1""",
                user.id,
            )
            if not row:
                await update.effective_message.reply_text("ℹ️ You have no pending or active AI Quiz Arena session.")
                return
            counts = await c.fetchrow(
                """SELECT
                     COUNT(*) FILTER(WHERE chat_type='private' AND status='joined')::int AS private_count,
                     COUNT(*) FILTER(WHERE chat_type IN ('group','supergroup') AND status='joined')::int AS group_count
                   FROM arena_destinations WHERE session_id=$1""",
                row["id"],
            )
            creator_registered = await c.fetchval(
                """SELECT EXISTS(
                     SELECT 1 FROM arena_destinations
                     WHERE session_id=$1 AND chat_id=$2 AND status='joined'
                   )""",
                row["id"], row["creator_chat_id"],
            )
            invite_token = await c.fetchval(
                "SELECT token FROM arena_invites WHERE session_id=$1 ORDER BY created_at DESC LIMIT 1",
                row["id"],
            )
        private_count = int(counts["private_count"] or 0)
        group_count = int(counts["group_count"] or 0)
        if not creator_registered:
            if row["creator_chat_type"] == ChatType.PRIVATE:
                private_count += 1
            elif row["creator_chat_type"] in (ChatType.GROUP, ChatType.SUPERGROUP):
                group_count += 1
        questions = row["questions"] or []
        if isinstance(questions, str):
            try:
                questions = json.loads(questions)
            except Exception:
                questions = []
        cfg = self.configs.get(user.id)
        if (
            row["status"] == "draft"
            and cfg
            and cfg.get("session_id") == row["id"]
            and len(questions) == int(row["question_count"])
        ):
            buttons = [[InlineKeyboardButton("▶️ START QUIZ", callback_data="arena:start")]]
            if invite_token:
                buttons.append([
                    InlineKeyboardButton("👤 INVITE FRIENDS", switch_inline_query=f"arena_invite_friend_{invite_token}"),
                    InlineKeyboardButton("👥 INVITE GROUPS", switch_inline_query=f"arena_invite_group_{invite_token}"),
                ])
            reply_markup = InlineKeyboardMarkup(buttons)

        expiry = row["invite_expires_at"]
        expiry_text = expiry.astimezone(timezone.utc).strftime("%H:%M UTC") if expiry else "not set"
        await update.effective_message.reply_text(
            f"📊 AI QUIZ ARENA STATUS\\n\\n"
            f"🆔 {row['session_code'] or row['id']}\\n"
            f"📖 {row['chapter']}\\n"
            f"📚 Questions: {row['question_count']}\\n"
            f"📍 Status: {row['status'].upper()}\\n"
            f"👤 Private chats: {private_count}/10\\n"
            f"👥 Groups: {group_count}/5\\n"
            f"❓ Current question: {max(0, int(row['current_index']) + 1)}"
            + (f"\\n⌛ Invitation expiry: {expiry_text}" if row["status"] in ("draft","generating","ready") else ""),
            reply_markup=reply_markup,
        )

    async def stop_command(self, update, context):
        user, chat = update.effective_user, update.effective_chat
        if not user or not chat:
            return
        # Only the session creator may stop the complete synchronized session.
        await self.stop_for_chat(chat.id, user.id, context, message=update.effective_message)

    async def stop_for_chat(self, chat_id, user_id, context, message=None):
        """Cancel the complete synchronized Arena session, not just one destination."""
        cfg = self.configs.pop(user_id, None)
        cancelled_ids = []

        async with self.db.pool.acquire() as c:
            # Only the session creator can stop the synchronized session.
            row = await c.fetchrow(
                """
                SELECT s.id, s.creator_id
                FROM arena_sessions s
                WHERE s.status IN ('draft','generating','ready','active')
                  AND s.creator_id=$1
                ORDER BY s.created_at DESC
                LIMIT 1
                """,
                user_id
            )

            if not row and cfg and cfg.get("session_id"):
                row = await c.fetchrow(
                    "SELECT id,creator_id FROM arena_sessions WHERE id=$1 AND creator_id=$2",
                    cfg["session_id"], user_id
                )

        if row:
            sid = row["id"]
            # Serialize cancellation against question delivery/finalization.
            lock = self.session_locks.setdefault(sid, asyncio.Lock())
            async with lock:
                async with self.db.pool.acquire() as c:
                    result = await c.execute(
                        """UPDATE arena_sessions
                           SET status='cancelled', ended_at=NOW()
                           WHERE id=$1 AND status IN ('draft','generating','ready','active')""",
                        sid
                    )
                    if result.endswith("1"):
                        await c.execute(
                            """UPDATE arena_destinations SET status='stopped'
                               WHERE session_id=$1 AND status='joined'""",
                            sid
                        )
                        await c.execute("DELETE FROM arena_group_locks WHERE session_id=$1", sid)
                        cancelled_ids.append(sid)

        # Stop background generation and scheduled question jobs.
        for sid in cancelled_ids:
            task = self.preparation_tasks.pop(sid, None)
            if task and not task.done():
                task.cancel()
            self.preparation_errors.pop(sid, None)
            for job in context.job_queue.jobs():
                data = getattr(job, "data", None) or {}
                if data.get("session_id") == sid:
                    job.schedule_removal()

        if message:
            if cancelled_ids:
                await message.reply_text(
                    "🛑 AI Quiz Arena stopped completely. All invited groups and chats "
                    "have been removed from this quiz. You can start a new quiz with /quiz."
                )
            else:
                await message.reply_text(
                    "ℹ️ No running or prepared Arena quiz was found. You can start one with /quiz."
                )

    async def _leaderboard(self, context, sid):
        async with self.db.pool.acquire() as c:
            session = await c.fetchrow(
                "SELECT chapter,question_count FROM arena_sessions WHERE id=$1",
                sid,
            )
            rows = await c.fetch(
                """SELECT a.user_id,a.username,a.first_name,a.last_name,a.chat_id,d.title,
                    SUM(a.points)::int AS score,
                    COUNT(*) FILTER(WHERE a.is_correct)::int AS correct,
                    COUNT(*) FILTER(WHERE a.selected_index>=0 AND NOT a.is_correct)::int AS wrong,
                    GREATEST(s.question_count - COUNT(*) FILTER(WHERE a.selected_index>=0), 0)::int AS unanswered
                   FROM arena_answers a
                   JOIN arena_destinations d ON d.session_id=a.session_id AND d.chat_id=a.chat_id
                   JOIN arena_sessions s ON s.id=a.session_id
                   WHERE a.session_id=$1 AND d.status IN ('joined','failed')
                   GROUP BY a.user_id,a.username,a.first_name,a.last_name,a.chat_id,d.title,s.question_count""",
                sid,
            )
            group_rows = await c.fetch(
                """SELECT d.chat_id,d.title,d.username,
                          COUNT(DISTINCT p.user_id)::int AS participants,
                          COALESCE(SUM(a.points),0)::int AS total_score,
                          ROUND(
                            COALESCE(SUM(a.points),0)::numeric /
                            NULLIF(COUNT(DISTINCT p.user_id),0), 2
                          ) AS average_score
                   FROM arena_destinations d
                   JOIN arena_participants p
                     ON p.session_id=d.session_id AND p.chat_id=d.chat_id
                   LEFT JOIN arena_answers a
                     ON a.session_id=p.session_id AND a.user_id=p.user_id
                    AND a.chat_id=p.chat_id
                   WHERE d.session_id=$1
                     AND d.chat_type IN ('group','supergroup')
                     AND d.status IN ('joined','failed')
                   GROUP BY d.chat_id,d.title,d.username
                   HAVING COUNT(DISTINCT p.user_id) > 0
                   ORDER BY average_score DESC,total_score DESC,d.title ASC""",
                sid,
            )
            destinations = await c.fetch(
                "SELECT chat_id FROM arena_destinations WHERE session_id=$1 AND status IN ('joined','failed')",
                sid,
            )

        combined = {}
        for r in rows:
            u = combined.setdefault(
                r["user_id"],
                {"name": r["first_name"] or r["username"] or str(r["user_id"]),
                 "score": 0, "correct": 0, "wrong": 0, "unanswered": 0, "places": []},
            )
            u["score"] += r["score"]
            u["correct"] += r["correct"]
            u["wrong"] += r["wrong"]
            u["unanswered"] += r["unanswered"]
            u["places"].append("Private" if r["chat_id"] > 0 else r["title"])

        ranked = sorted(
            combined.items(),
            key=lambda x: (-x[1]["score"], -x[1]["correct"], x[1]["wrong"], x[0]),
        )
        lines = [
            f"🏆 <b>{self._escape(session['chapter'])}</b>",
            f"👥 Attended participants: <b>{len(ranked)}</b>",
            "━━━━━━━━━━━━━━━━━━",
            "🏅 <b>INDIVIDUAL LEADERBOARD</b>",
        ]
        for rank, (uid, u) in enumerate(ranked, 1):
            places = ", ".join(dict.fromkeys(u["places"]))
            lines.append(
                f"<blockquote><b>#{rank} · <a href=\"tg://user?id={uid}\">{self._escape(u['name'])}</a></b>\n"
                f"⭐ Score: <b>{u['score']}</b>  |  ✅ {u['correct']}  |  ❌ {u['wrong']}  |  ⏭ {u['unanswered']}\n"
                f"📍 {self._escape(places)}</blockquote>"
            )

        if group_rows:
            lines.extend(["━━━━━━━━━━━━━━━━━━", "👥 <b>GROUP LEADERBOARD</b>"])
            for rank, g in enumerate(group_rows, 1):
                title = self._escape(g["title"] or "Group")
                username = g["username"]
                if username and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
                    title = f'<a href="https://t.me/{username}">{title}</a>'
                lines.append(
                    f"<blockquote><b>#{rank} · {title}</b>\n"
                    f"👤 Attended: <b>{g['participants']}</b>\n"
                    f"📊 Average score: <b>{float(g['average_score']):.2f}</b></blockquote>"
                )

        text = "\n".join(lines) if ranked or group_rows else (
            f"🏆 <b>{self._escape(session['chapter'])}</b>\nNo participants recorded."
        )
        semaphore = asyncio.Semaphore(10)

        async def deliver(destination):
            async with semaphore:
                try:
                    await context.bot.send_message(
                        destination["chat_id"], text, parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    log.warning("Arena leaderboard delivery failed chat=%s: %s", destination["chat_id"], e)

        await asyncio.gather(*(deliver(d) for d in destinations))

    @staticmethod
    def _escape(value):
        import html
        return html.escape(str(value or ""))
