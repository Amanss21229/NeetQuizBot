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
            await c.execute("CREATE INDEX IF NOT EXISTS idx_arena_bank_chapter ON arena_question_bank(chapter_key, language)")
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
            await c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_arena_single_active ON arena_sessions ((1)) WHERE status IN ('generating','ready','active')")
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
        """Resume durable sessions after a process restart."""
        async with self.db.pool.acquire() as c:
            # A process can die during generation; such sessions cannot safely resume.
            await c.execute("UPDATE arena_sessions SET status='failed',ended_at=NOW() WHERE status='generating'")
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
        balance_row = await self.db.get_ai_credits(user.id)
        balance = int(balance_row["balance"]) if balance_row else 0
        await self.db.add_user(user.id, user.username, user.first_name, user.last_name)
        self.configs[user.id] = {"chapter": chapter, "chat_id": chat.id, "chat_type": chat.type, "title": chat.title or user.first_name, "language": None, "count": None, "seconds": None}
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
                async with self.db.pool.acquire() as c:
                    await c.execute("INSERT INTO arena_sessions(id,creator_id,chapter,chapter_key,language,question_count,seconds,questions,status) VALUES($1,$2,$3,$4,$5,$6,$7,'[]'::jsonb,'draft')", draft_id, user_id, cfg["chapter"], self.chapter_key(cfg["chapter"]), cfg["language"], cfg["count"], cfg["seconds"])
                    await c.execute("INSERT INTO arena_invites(token,session_id,creator_id) VALUES($1,$2,$3)", invite_token, draft_id, user_id)
                cfg["session_id"] = draft_id
                # Inline mode opens Telegram's chat picker; the user chooses the destination.
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📨 Invite groups / users", switch_inline_query=f"arena_invite_{invite_token}")],
                    [InlineKeyboardButton("✅ Done — Start quiz", callback_data="arena:start")]
                ])
                cfg["invite_token"] = invite_token
                cfg["cost"] = cost
                await context.bot.send_message(cfg["chat_id"],
                    f"📨 *INVITATION & START*\n\n📖 {cfg['chapter']}\n🌐 {cfg['language'].title()}\n❓ {cfg['count']} questions\n⏱ {cfg['seconds']} sec/question\n💳 Cost: {cost} credit(s)\n\nInvite people or groups using the first button. Then press Done.\n\nNote: the bot must be present in a group to publish its quiz.",
                    reply_markup=kb, parse_mode="Markdown")
            else:
                pass
            return True
        if action == "start":
            cfg = self.configs.get(user_id)
            if not cfg:
                await q.answer("Configuration expired.", show_alert=True); return True
            await q.answer("Preparing quiz…")
            await self.start_session(user_id, cfg, context, q.message)
            return True
        if action in ("accept", "reject"):
            session_id = parts[2]
            if action == "reject":
                try:
                    if q.message:
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
                await q.answer(
                    f"To accept, send /accept {session_id} "
                    "in the chat where this invitation was posted. "
                    "In groups, only an admin can accept.",
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
                    row = await c.fetchrow("SELECT status FROM arena_sessions WHERE id=$1", session_id)
                    if not row or row["status"] not in ("draft", "generating", "ready"):
                        await q.answer("This quiz is no longer accepting destinations.", show_alert=True); return True
                    await c.execute("INSERT INTO arena_destinations(session_id,chat_id,chat_type,title) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING", session_id, chat.id, chat.type, chat.title or "Private")
                await q.answer("Quiz invitation accepted")
                await q.edit_message_text("✅ Quiz invitation accepted. This destination will join the synchronized quiz.")
            except Exception as e:
                log.exception("arena invite accept failed: %s", e)
                await q.answer("Unable to accept this invitation.", show_alert=True)
            return True
        if action == "stop":
            await self.stop_for_chat(q.message.chat.id, user_id, context)
            await q.answer("Quiz stopped")
            return True
        return True

    async def start_session(self, user_id: int, cfg: dict, context, status_message):
        session_id = cfg["session_id"]
        cost = int(cfg["cost"])
        try:
            async with self.db.pool.acquire() as c:
                # The partial unique index prevents parallel sessions globally.
                await c.execute("UPDATE arena_sessions SET status='generating' WHERE id=$1 AND creator_id=$2 AND status='draft'", session_id, user_id)
        except Exception as e:
            if "uq_arena_single_active" in str(e) or "duplicate key" in str(e).lower():
                await status_message.reply_text("⏳ Another AI Quiz Arena session is already running or being prepared. Please wait until it finishes.")
                return
            raise
        try:
            # Reuse cached bank first. Cache contains a maximum of 1,000 unique questions per chapter.
            async with self.db.pool.acquire() as c:
                bank_count = await c.fetchval("SELECT COUNT(*) FROM arena_question_bank WHERE chapter_key=$1 AND language=$2", self.chapter_key(cfg["chapter"]), cfg["language"])
                if bank_count >= 1000:
                    rows = await c.fetch("SELECT question,options,correct_index,explanation FROM arena_question_bank WHERE chapter_key=$1 AND language=$2 ORDER BY random() LIMIT $3", self.chapter_key(cfg["chapter"]), cfg["language"], cfg["count"])
                    questions = [self._row_question(r) for r in rows]
                else:
                    questions = []
            if len(questions) < cfg["count"]:
                generated = await self._generate(cfg["chapter"], cfg["language"], cfg["count"])
                questions = generated
                await self._save_bank(cfg["chapter"], cfg["language"], generated)
            if len(questions) != cfg["count"]:
                raise RuntimeError("Question generator returned an incomplete set")
            # Atomic credit debit after generation succeeds; failed generations cost nothing.
            debit = await self.db.consume_ai_credit(user_id, cost, "ARENA_QUIZ_CREATE", {"source":"ai_quiz_arena","session_id":session_id,"questions":cfg["count"]})
            if not debit:
                raise RuntimeError("INSUFFICIENT_CREDITS")
            async with self.db.pool.acquire() as c:
                await c.execute("UPDATE arena_sessions SET questions=$2::jsonb,status='ready' WHERE id=$1", session_id, json.dumps(questions, ensure_ascii=False))
                await c.execute("INSERT INTO arena_destinations(session_id,chat_id,chat_type,title) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING", session_id, cfg["chat_id"], cfg["chat_type"], cfg["title"])
                await c.execute("UPDATE arena_invites SET session_id=$2 WHERE token=$1", cfg["invite_token"], session_id)
            cfg["session_id"] = session_id
            await status_message.reply_text(f"✅ Quiz ready. {cfg['count']} unique questions loaded. Credits used: {cost}. Starting in 5 seconds.")
            context.job_queue.run_once(self._tick, when=5, data={"session_id":session_id}, name=f"arena:{session_id}")
            self.configs.pop(user_id, None)
        except Exception as e:
            async with self.db.pool.acquire() as c:
                await c.execute("UPDATE arena_sessions SET status='failed',ended_at=NOW() WHERE id=$1", session_id)
            log.exception("Arena session setup failed: %s", e)
            message = "❌ Quiz setup failed. No credits were deducted." if str(e) != "INSUFFICIENT_CREDITS" else "❌ Credits changed before quiz start; please check /credits."
            await status_message.reply_text(message)

    async def _generate(self, chapter: str, language: str, count: int) -> list[dict]:
        if not self.provider:
            raise RuntimeError("Gemini API is not configured. Set GEMINI_API_KEY.")
        lang = "Hindi" if language == "hindi" else "English"
        prompt = f'''Create exactly {count} distinct NEET-UG multiple-choice questions for the NCERT chapter: {chapter}. Language: {lang}. Use only current NEET-UG syllabus scope and current NCERT concepts. Each question must have exactly four options and exactly one correct answer. Do not invent facts, ambiguous claims, or out-of-syllabus material. Avoid repeats and near-duplicates. For every item, independently solve/check the answer and provide a concise explanation. Return ONLY valid JSON array with objects: question, options (array of exactly 4 strings), correct_index (0-3), explanation. Append the literal text "【@DrQuizRobot】" at the end of every question. No markdown fences.'''
        raw = await self.provider.generate(
            [ChatMessage(role="user", content=prompt)],
            "You are a careful NEET-UG question writer. Accuracy is more important than speed. If uncertain about a fact, do not include it.",
            max_output_tokens=8192,
            timeout_seconds=120,
        )
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
        data = json.loads(raw)
        if not isinstance(data, list) or len(data) != count:
            raise ValueError("AI output did not contain the exact requested question count")
        out, seen = [], set()
        for item in data:
            q = str(item.get("question", "")).strip()
            opts = item.get("options")
            idx = item.get("correct_index")
            explanation = str(item.get("explanation", "")).strip()
            if not q.endswith("【@DrQuizRobot】"):
                q = q.rstrip() + " 【@DrQuizRobot】"
            if not q or not isinstance(opts, list) or len(opts) != 4 or any(not str(x).strip() for x in opts) or len(set(map(str, opts))) != 4 or not isinstance(idx, int) or idx not in range(4) or not explanation:
                raise ValueError("AI produced an invalid question structure")
            norm = re.sub(r"[^a-z0-9]+", "", q.lower())
            if norm in seen:
                raise ValueError("AI produced duplicate questions")
            seen.add(norm)
            out.append({"question":q,"options":[str(x).strip() for x in opts],"correct_index":idx,"explanation":explanation})
        # A second independent model pass catches inconsistencies, but cannot mathematically guarantee factual perfection.
        review_prompt = "Audit every question below for factual correctness, NCERT alignment, latest NEET-UG scope, exactly one correct option, and explanation consistency. Return JSON only: {\"valid\":true/false,\"issues\":[...]} . If any uncertainty or error exists, valid must be false.\n" + json.dumps(out, ensure_ascii=False)
        review = await self.provider.generate(
            [ChatMessage(role="user", content=review_prompt)],
            "You are an independent strict NEET question auditor. Reject uncertain or incorrect questions.",
            max_output_tokens=1200,
            timeout_seconds=120,
        )
        review = re.sub(r"^```(?:json)?\s*|\s*```$", "", review.strip(), flags=re.I)
        verdict = json.loads(review)
        if verdict.get("valid") is not True or verdict.get("issues"):
            raise ValueError("Question audit rejected the generated set: " + str(verdict.get("issues", []))[:500])
        return out

    @staticmethod
    def _row_question(r):
        return {"question":r["question"],"options":r["options"],"correct_index":int(r["correct_index"]),"explanation":r["explanation"]}

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
                            question_hash
                        )
                        VALUES(
                            $1,$2,$3,$4,$5::jsonb,$6,$7,$8
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
                        h
                    )

                    if result.endswith("1"):
                        current += 1

    async def inline_query(self, update, context):
        query = update.inline_query.query.strip()
        if not query.startswith("arena_invite_"):
            return False
        token = query.removeprefix("arena_invite_")
        async with self.db.pool.acquire() as c:
            row = await c.fetchrow("""SELECT i.session_id,s.chapter,s.language,s.question_count,s.seconds,s.status FROM arena_invites i JOIN arena_sessions s ON s.id=i.session_id WHERE i.token=$1""", token)
        if not row or row["status"] not in ("draft", "generating", "ready"):
            await update.inline_query.answer([], cache_time=0, is_personal=True)
            return True
        text = (
            f"📨 NEET QUIZ INVITATION\n\n"
            f"📖 Chapter: {row['chapter']}\n"
            f"🌐 Language: {row['language'].title()}\n"
            f"❓ Questions: {row['question_count']}\n"
            f"⏱ Time per question: {row['seconds']} sec\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"To accept this invitation:\n\n"
            f"👥 Group: A group admin must send:\n"
            f"/accept {row['session_id']}\n\n"
            f"👤 Private: The recipient must start the bot "
            f"and send the same command in this private chat.\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"One user can participate in only one destination "
            f"for this quiz."
        )
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Accept (Instructions)",
                    callback_data=f"arena:accept:{row['session_id']}"
                ),
                InlineKeyboardButton(
                    "❌ Reject",
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
            async with self.db.pool.acquire() as c:
                session = await c.fetchrow("SELECT * FROM arena_sessions WHERE id=$1", sid)
                if not session or session["status"] != "active" and session["status"] != "ready": return
                next_index = int(session["current_index"]) + 1
                questions = session["questions"]
                destinations = await c.fetch("SELECT * FROM arena_destinations WHERE session_id=$1 AND status='joined'", sid)
                if next_index >= len(questions):
                    await c.execute("UPDATE arena_sessions SET status='finished',ended_at=NOW() WHERE id=$1", sid)
                    await self._leaderboard(context, sid)
                    return
                await c.execute("UPDATE arena_sessions SET status='active',current_index=$2,started_at=COALESCE(started_at,NOW()),question_started_at=NOW() WHERE id=$1", sid, next_index)
            qdata = questions[next_index]
            for dest in destinations:
                try:
                    poll = await context.bot.send_poll(chat_id=dest["chat_id"], question=qdata["question"], options=qdata["options"], type="quiz", correct_option_id=int(qdata["correct_index"]), is_anonymous=False, open_period=int(session["seconds"]), explanation=qdata["explanation"][:180])
                    self.polls[poll.poll.id] = {"session_id":sid,"chat_id":dest["chat_id"],"question_index":next_index,"correct_index":int(qdata["correct_index"])}
                    async with self.db.pool.acquire() as c:
                        await c.execute("INSERT INTO arena_poll_map(poll_id,session_id,chat_id,question_index,correct_index) VALUES($1,$2,$3,$4,$5) ON CONFLICT(poll_id) DO NOTHING", poll.poll.id, sid, dest["chat_id"], next_index, int(qdata["correct_index"]))
                except (Forbidden, BadRequest) as e:
                    log.warning("Arena poll delivery failed chat=%s: %s", dest["chat_id"], e)
                    async with self.db.pool.acquire() as c:
                        await c.execute("UPDATE arena_destinations SET status='failed' WHERE session_id=$1 AND chat_id=$2", sid, dest["chat_id"])
            context.job_queue.run_once(self._tick, when=int(session["seconds"]), data={"session_id":sid}, name=f"arena:{sid}")

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
        correct = selected == info["correct_index"]
        points = 4 if correct else (-1 if selected >= 0 else 0)
        await self.db.add_user(user.id, user.username, user.first_name, user.last_name)
        async with self.db.pool.acquire() as c:
            async with c.transaction():
                await c.execute("INSERT INTO arena_participants(session_id,user_id,chat_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", info["session_id"], user.id, info["chat_id"])
                participant_chat = await c.fetchval("SELECT chat_id FROM arena_participants WHERE session_id=$1 AND user_id=$2", info["session_id"], user.id)
                # A participant is locked to the first group/private chat in which they answer.
                if participant_chat != info["chat_id"]:
                    return True
                await c.execute("""INSERT INTO arena_answers(session_id,chat_id,user_id,username,first_name,last_name,question_index,selected_index,is_correct,points) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(session_id,user_id,question_index) DO UPDATE SET selected_index=EXCLUDED.selected_index,is_correct=EXCLUDED.is_correct,points=EXCLUDED.points,answered_at=NOW()""", info["session_id"], info["chat_id"], user.id, user.username, user.first_name, user.last_name, info["question_index"], selected, correct, points)
        return True

    async def accept_command(self, update, context):
        user, chat = update.effective_user, update.effective_chat
        if not user or not chat or not context.args:
            await update.effective_message.reply_text("Usage: /accept SESSION_ID")
            return
        session_id = context.args[0].strip()
        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            try:
                member = await context.bot.get_chat_member(chat.id, user.id)
                if member.status not in ("administrator", "creator"):
                    await update.effective_message.reply_text("Only group admins can accept this invitation.")
                    return
            except Exception:
                await update.effective_message.reply_text("Unable to verify group admin permissions.")
                return
        async with self.db.pool.acquire() as c:
            row = await c.fetchrow("SELECT status FROM arena_sessions WHERE id=$1", session_id)
            if not row or row["status"] not in ("draft", "generating", "ready"):
                await update.effective_message.reply_text("This invitation is invalid or no longer accepting destinations.")
                return
            await c.execute("INSERT INTO arena_destinations(session_id,chat_id,chat_type,title) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING", session_id, chat.id, chat.type, chat.title or "Private")
        await update.effective_message.reply_text("✅ Invitation accepted. This chat will join the same synchronized quiz.")

    async def stop_command(self, update, context):
        user, chat = update.effective_user, update.effective_chat
        if not user or not chat: return
        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            try:
                member = await context.bot.get_chat_member(chat.id, user.id)
                if member.status not in ("administrator", "creator"):
                    await update.effective_message.reply_text("Only group admins can stop this quiz."); return
            except Exception:
                await update.effective_message.reply_text("Unable to verify admin permissions."); return
        await self.stop_for_chat(chat.id, user.id, context, message=update.effective_message)

    async def stop_for_chat(self, chat_id, user_id, context, message=None):
        async with self.db.pool.acquire() as c:
            row = await c.fetchrow("SELECT s.id FROM arena_sessions s JOIN arena_destinations d ON d.session_id=s.id WHERE d.chat_id=$1 AND d.status='joined' AND s.status='active'", chat_id)
            if not row:
                if message: await message.reply_text("No active Arena quiz in this chat.")
                return
            await c.execute("UPDATE arena_destinations SET status='stopped' WHERE session_id=$1 AND chat_id=$2", row["id"], chat_id)
            left = await c.fetchval("SELECT COUNT(*) FROM arena_destinations WHERE session_id=$1 AND status='joined'", row["id"])
            if not left: await c.execute("UPDATE arena_sessions SET status='finished',ended_at=NOW() WHERE id=$1", row["id"])
        if message: await message.reply_text("🛑 Quiz stopped for this chat. This chat will not receive the final leaderboard.")

    async def _leaderboard(self, context, sid):
        async with self.db.pool.acquire() as c:
            session = await c.fetchrow("SELECT chapter FROM arena_sessions WHERE id=$1", sid)
            rows = await c.fetch("""SELECT a.user_id,a.username,a.first_name,a.last_name,a.chat_id, d.title,
                SUM(a.points)::int AS score, COUNT(*) FILTER(WHERE a.is_correct)::int AS correct,
                COUNT(*) FILTER(WHERE a.selected_index>=0 AND NOT a.is_correct)::int AS wrong,
                GREATEST(s.question_count - COUNT(*) FILTER(WHERE a.selected_index>=0), 0)::int AS unanswered
                FROM arena_answers a JOIN arena_destinations d ON d.session_id=a.session_id AND d.chat_id=a.chat_id
                JOIN arena_sessions s ON s.id=a.session_id
                WHERE a.session_id=$1 AND d.status='joined'
                GROUP BY a.user_id,a.username,a.first_name,a.last_name,a.chat_id,d.title,s.question_count
                ORDER BY score DESC,correct DESC,wrong ASC,unanswered ASC""", sid)
            destinations = await c.fetch("SELECT chat_id FROM arena_destinations WHERE session_id=$1 AND status='joined'", sid)
        # Combine a participant's entries across all destinations into one global row.
        combined = {}
        for r in rows:
            u = combined.setdefault(r["user_id"], {"name":r["first_name"] or r["username"] or str(r["user_id"]),"score":0,"correct":0,"wrong":0,"unanswered":0,"places":[]})
            u["score"] += r["score"]; u["correct"] += r["correct"]; u["wrong"] += r["wrong"]; u["unanswered"] += r["unanswered"]
            u["places"].append("Private" if r["chat_id"] > 0 else r["title"])
        ranked = sorted(combined.items(), key=lambda x:(-x[1]["score"],-x[1]["correct"],x[1]["wrong"],x[0]))
        lines = [f"🏆 <b>{self._escape(session['chapter'])}</b>", f"👥 Participants: <b>{len(ranked)}</b>", "━━━━━━━━━━━━━━━━━━"]
        for rank,(uid,u) in enumerate(ranked,1):
            places = ", ".join(dict.fromkeys(u["places"]))
            lines.append(f"<blockquote><b>#{rank} · <a href=\"tg://user?id={uid}\">{self._escape(u['name'])}</a></b>\n⭐ Score: <b>{u['score']}</b>  |  ✅ {u['correct']}  |  ❌ {u['wrong']}  |  ⏭ {u['unanswered']}\n📍 {self._escape(places)}</blockquote>")
        text = "\n".join(lines) if ranked else f"🏆 <b>{self._escape(session['chapter'])}</b>\nNo participants recorded."
        for d in destinations:
            try: await context.bot.send_message(d["chat_id"], text, parse_mode="HTML", disable_web_page_preview=True)
            except Exception as e: log.warning("Arena leaderboard delivery failed: %s", e)

    @staticmethod
    def _escape(value):
        import html
        return html.escape(str(value or ""))
