-- NEET Quiz Arena additive migration for Neon PostgreSQL
-- SAFE / RE-RUNNABLE:
--   * No rows are deleted.
--   * No table is dropped or truncated.
--   * Existing tables are preserved; missing columns/tables are added only.
--   * The old global Arena index and legacy uniqueness constraint are removed
--     because they block the agreed per-group concurrency / per-language bank.
--     Removing these definitions does NOT delete any database records.

BEGIN;

CREATE TABLE IF NOT EXISTS arena_question_bank (
    id BIGSERIAL PRIMARY KEY,
    chapter_key TEXT NOT NULL,
    chapter TEXT NOT NULL,
    language TEXT NOT NULL,
    question TEXT NOT NULL,
    options JSONB NOT NULL,
    correct_index SMALLINT NOT NULL CHECK (correct_index BETWEEN 0 AND 3),
    explanation TEXT NOT NULL DEFAULT '',
    question_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE arena_question_bank
    ADD COLUMN IF NOT EXISTS pyq_year INTEGER;
ALTER TABLE arena_question_bank
    ADD COLUMN IF NOT EXISTS question_type TEXT NOT NULL DEFAULT 'single_correct';
ALTER TABLE arena_question_bank
    ADD COLUMN IF NOT EXISTS detailed_solution TEXT NOT NULL DEFAULT '';

-- Remove only the obsolete constraint definition; no rows are removed.
ALTER TABLE arena_question_bank
    DROP CONSTRAINT IF EXISTS arena_question_bank_chapter_key_question_hash_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_arena_bank_chapter_language_hash'
          AND conrelid = 'arena_question_bank'::regclass
    ) THEN
        ALTER TABLE arena_question_bank
            ADD CONSTRAINT uq_arena_bank_chapter_language_hash
            UNIQUE (chapter_key, language, question_hash);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_arena_bank_chapter
    ON arena_question_bank(chapter_key, language);

CREATE TABLE IF NOT EXISTS arena_chapter_sources (
    id BIGSERIAL PRIMARY KEY,
    chapter_key TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'english',
    source_type TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_text TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_arena_chapter_sources_lookup
    ON arena_chapter_sources(chapter_key,language,source_type);

CREATE OR REPLACE FUNCTION arena_question_bank_cap_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    existing_count INTEGER;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.chapter_key || ':' || NEW.language, 0)
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

-- Recreate only the trigger definition. Existing question-bank rows remain.
DROP TRIGGER IF EXISTS trg_arena_question_bank_cap ON arena_question_bank;
CREATE TRIGGER trg_arena_question_bank_cap
BEFORE INSERT ON arena_question_bank
FOR EACH ROW
EXECUTE FUNCTION arena_question_bank_cap_guard();

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
);

ALTER TABLE arena_sessions
    ADD COLUMN IF NOT EXISTS question_started_at TIMESTAMPTZ;
ALTER TABLE arena_sessions
    ADD COLUMN IF NOT EXISTS session_code TEXT;
ALTER TABLE arena_sessions
    ADD COLUMN IF NOT EXISTS invite_expires_at TIMESTAMPTZ;
ALTER TABLE arena_sessions
    ADD COLUMN IF NOT EXISTS creator_chat_id BIGINT;
ALTER TABLE arena_sessions
    ADD COLUMN IF NOT EXISTS creator_chat_type TEXT;
ALTER TABLE arena_sessions
    ADD COLUMN IF NOT EXISTS creator_chat_title TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_arena_session_code
    ON arena_sessions(session_code)
    WHERE session_code IS NOT NULL;

-- This index prevented all creators/groups from running independent sessions.
-- Dropping an index changes no table data.
DROP INDEX IF EXISTS uq_arena_single_active;

CREATE TABLE IF NOT EXISTS arena_poll_map (
    poll_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    question_index INTEGER NOT NULL,
    correct_index SMALLINT NOT NULL
);

CREATE TABLE IF NOT EXISTS arena_destinations (
    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    chat_type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'joined',
    PRIMARY KEY (session_id, chat_id)
);

ALTER TABLE arena_destinations
    ADD COLUMN IF NOT EXISTS username TEXT;

CREATE TABLE IF NOT EXISTS arena_group_locks (
    group_id BIGINT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Preserve existing active group sessions by backfilling their locks.
INSERT INTO arena_group_locks(group_id,session_id)
SELECT DISTINCT ON (d.chat_id) d.chat_id,d.session_id
FROM arena_destinations d
JOIN arena_sessions s ON s.id=d.session_id
WHERE d.chat_type IN ('group','supergroup')
  AND d.status='joined'
  AND s.status IN ('ready','active')
ORDER BY d.chat_id,s.created_at DESC
ON CONFLICT(group_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS arena_invite_responses (
    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    response TEXT NOT NULL CHECK (response IN ('accepted', 'rejected')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, chat_id)
);

CREATE TABLE IF NOT EXISTS arena_waiting_members (
    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, user_id)
);

CREATE TABLE IF NOT EXISTS arena_participants (
    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (session_id, user_id)
);

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
    PRIMARY KEY (session_id, user_id, question_index)
);

CREATE TABLE IF NOT EXISTS arena_invites (
    token TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES arena_sessions(id) ON DELETE CASCADE,
    creator_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMIT;
