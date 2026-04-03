import asyncio
import asyncpg
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Union

# Setup logger
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        # Cache to reduce database queries and compute hours
        self._cache = {}
        self._cache_ttl = {
            'force_join_groups': 300,  # 5 minutes
            'group_language': 60,  # 1 minute per group
            'admin_list': 300,  # 5 minutes
        }
    
    def _get_cache(self, key: str) -> Optional[any]:
        """Get value from cache if not expired"""
        if key in self._cache:
            data, timestamp, ttl = self._cache[key]
            if time.time() - timestamp < ttl:
                return data
            else:
                del self._cache[key]
        return None
    
    def _set_cache(self, key: str, value: any, ttl: int):
        """Set value in cache with TTL"""
        self._cache[key] = (value, time.time(), ttl)
    
    def _invalidate_cache(self, key: str):
        """Invalidate specific cache key"""
        if key in self._cache:
            del self._cache[key]
    
    async def init_pool(self):
        """Initialize database connection pool with aggressive timeouts to reduce Neon DB compute hours"""
        self.pool = await asyncpg.create_pool(
            os.environ.get("DATABASE_URL"),
            min_size=0,  # No minimum connections = no idle connections eating compute hours
            max_size=3,  # Reduced from 10 to 3 for lower resource usage
            max_queries=5000,  # Recycle connections after 5000 queries
            max_inactive_connection_lifetime=60.0,  # Close connections idle for 60 seconds
            command_timeout=10.0,  # 10 second timeout for queries
            statement_cache_size=0  # Disable statement cache to reduce memory
        )
        await self.create_tables()
    
    async def create_tables(self):
        """Create all necessary tables"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            # Users table
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
                )
            """)
            
            # Groups table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id BIGINT PRIMARY KEY,
                    title TEXT,
                    type TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    replies_enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Migration: Add replies_enabled column if it doesn't exist (for existing databases)
            await conn.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='groups' AND column_name='replies_enabled'
                    ) THEN
                        ALTER TABLE groups ADD COLUMN replies_enabled BOOLEAN DEFAULT TRUE;
                    END IF;
                END $$;
            """)
            
            # Migration: Add language_preference column if it doesn't exist (for existing databases)
            await conn.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='groups' AND column_name='language_preference'
                    ) THEN
                        ALTER TABLE groups ADD COLUMN language_preference TEXT DEFAULT 'english';
                    END IF;
                END $$;
            """)

            # Migration: Add language_preference column to users table if it doesn't exist
            await conn.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='users' AND column_name='language_preference'
                    ) THEN
                        ALTER TABLE users ADD COLUMN language_preference TEXT DEFAULT 'english';
                    END IF;
                END $$;
            """)

            # Migration: Add clone_bot_id to groups
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='groups' AND column_name='clone_bot_id'
                    ) THEN
                        ALTER TABLE groups ADD COLUMN clone_bot_id BIGINT DEFAULT NULL;
                    END IF;
                END $$;
            """)

            # Migration: Add clone_bot_id to users
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='users' AND column_name='clone_bot_id'
                    ) THEN
                        ALTER TABLE users ADD COLUMN clone_bot_id BIGINT DEFAULT NULL;
                    END IF;
                END $$;
            """)

            # Clone bots table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS clone_bots (
                    id SERIAL PRIMARY KEY,
                    bot_token TEXT UNIQUE NOT NULL,
                    bot_id BIGINT UNIQUE NOT NULL,
                    bot_name TEXT,
                    bot_username TEXT,
                    owner_id BIGINT NOT NULL,
                    owner_username TEXT,
                    owner_name TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    is_paused BOOLEAN DEFAULT FALSE,
                    pause_reason TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Poll mappings table (for clone bots to look up quiz data)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS poll_mappings (
                    poll_id TEXT PRIMARY KEY,
                    quiz_id INTEGER,
                    group_id BIGINT,
                    message_id BIGINT,
                    clone_bot_id BIGINT,
                    correct_option INTEGER,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Clone pending setup table (persists across bot restarts)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS clone_pending (
                    user_id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Admins table (create before inserting data)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    promoted_by BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # ✅ Ensure default owner is always admin
            await conn.execute("""
                INSERT INTO admins (user_id, username, first_name, promoted_by)
                VALUES (8147394357, 'aimforaiims007', 'Aman', 8147394357)
                ON CONFLICT (user_id) DO NOTHING
            """)
            
            # Quizzes table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS quizzes (
                    id SERIAL PRIMARY KEY,
                    message_id BIGINT,
                    from_group_id BIGINT,
                    quiz_text TEXT,
                    correct_option INTEGER,
                    options JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)


            
            # User scores per quiz
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_quiz_scores (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    group_id BIGINT,
                    quiz_id INTEGER REFERENCES quizzes(id),
                    selected_option INTEGER,
                    points INTEGER,
                    answered_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id, quiz_id, group_id)
                )
            """)
            
            # Group members table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS group_members (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    group_id BIGINT,
                    joined_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id, group_id)
                )
            """)

            # Quiz Solutions table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS quiz_solutions (
                    quiz_id INT PRIMARY KEY REFERENCES quizzes(id),
                    solution_type TEXT,
                    solution_content TEXT,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Custom Replies table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_replies (
                    id SERIAL PRIMARY KEY,
                    reply_type TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT,
                    file_id TEXT,
                    caption TEXT,
                    added_by BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Message Mapping table for user-admin communication
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS message_mapping (
                    forwarded_message_id BIGINT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Force Join Groups table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS force_join_groups (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT UNIQUE,
                    chat_username TEXT,
                    chat_title TEXT,
                    chat_type TEXT,
                    invite_link TEXT,
                    added_by BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Sent Messages table for tracking broadcast messages (for /delete command)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sent_messages (
                    id SERIAL PRIMARY KEY,
                    original_message_id BIGINT NOT NULL,
                    original_chat_id BIGINT NOT NULL,
                    sent_message_id BIGINT NOT NULL,
                    sent_chat_id BIGINT NOT NULL,
                    sent_by BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Custom Button Posts table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS button_posts (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    text TEXT NOT NULL,
                    buttons JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Create index for faster lookups
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_button_posts_user 
                ON button_posts(user_id)
            """)

    
    async def add_user(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None, clone_bot_id: Optional[int] = None):
        """Add or update user in database"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (id, username, first_name, last_name, clone_bot_id, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    username = $2,
                    first_name = $3,
                    last_name = $4,
                    clone_bot_id = COALESCE(users.clone_bot_id, EXCLUDED.clone_bot_id),
                    updated_at = NOW()
            """, user_id, username, first_name, last_name, clone_bot_id)
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user data by user ID"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, username, first_name, last_name, 
                       total_score, correct_answers, wrong_answers, unattempted,
                       created_at, updated_at
                FROM users
                WHERE id = $1
            """, user_id)
            return dict(row) if row else None
    
    async def add_group(self, group_id: int, title: str, group_type: str, clone_bot_id: Optional[int] = None):
        """Add or update group in database"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO groups (id, title, type, clone_bot_id, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    title = $2,
                    type = $3,
                    clone_bot_id = COALESCE(groups.clone_bot_id, EXCLUDED.clone_bot_id),
                    updated_at = NOW()
            """, group_id, title, group_type, clone_bot_id)
    
    async def add_group_member(self, user_id: int, group_id: int):
        """Add user to group"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO group_members (user_id, group_id)
                VALUES ($1, $2)
                ON CONFLICT (user_id, group_id) DO NOTHING
            """, user_id, group_id)
    
    async def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT user_id FROM admins WHERE user_id = $1", user_id
            )
            return result is not None
    
    async def add_admin(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None, promoted_by: Optional[int] = None):
        """Add admin to database"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO admins (user_id, username, first_name, promoted_by)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO NOTHING
            """, user_id, username, first_name, promoted_by)
    
    async def remove_admin(self, user_id: int):
        """Remove admin from database"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)
    
    async def get_all_admins(self) -> List[Dict]:
        """Get all admins"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM admins ORDER BY created_at")
            return [dict(row) for row in rows]
    
    async def add_quiz(self, message_id: int, from_group_id: int, quiz_text: str, correct_option: int, options: List[str]) -> int:
        """Add quiz to database and return quiz_id"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            quiz_id = await conn.fetchval("""
                INSERT INTO quizzes (message_id, from_group_id, quiz_text, correct_option, options)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING id
            """, message_id, from_group_id, quiz_text, correct_option, json.dumps(options))
            return quiz_id
    
    async def update_quiz_correct_option(self, quiz_id: int, correct_option: int):
        """Update correct option for an existing quiz"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE quizzes SET correct_option = $2
                WHERE id = $1
            """, quiz_id, correct_option)
    
    async def record_quiz_answer(self, user_id: int, group_id: int, quiz_id: int, selected_option: int, points: int):
        """Record user's quiz answer"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_quiz_scores (user_id, group_id, quiz_id, selected_option, points)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (user_id, quiz_id, group_id) DO NOTHING
            """, user_id, group_id, quiz_id, selected_option, points)
            
            # Update user total score
            await conn.execute("""
                UPDATE users SET 
                    total_score = total_score + $2,
                    correct_answers = correct_answers + CASE WHEN $2 = 4 THEN 1 ELSE 0 END,
                    wrong_answers = wrong_answers + CASE WHEN $2 = -1 THEN 1 ELSE 0 END,
                    unattempted = unattempted + CASE WHEN $2 = 0 THEN 1 ELSE 0 END,
                    updated_at = NOW()
                WHERE id = $1
            """, user_id, points)
    
    async def get_group_leaderboard(self, group_id: int) -> List[Dict]:
        """Get leaderboard for specific group"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.id, u.username, u.first_name, u.last_name,
                       COALESCE(SUM(uqs.points), 0) as score,
                       COUNT(CASE WHEN uqs.points = 4 THEN 1 END) as correct,
                       COUNT(CASE WHEN uqs.points = -1 THEN 1 END) as wrong,
                       COUNT(CASE WHEN uqs.points = 0 THEN 1 END) as unattempted
                FROM users u
                JOIN group_members gm ON u.id = gm.user_id
                LEFT JOIN user_quiz_scores uqs ON u.id = uqs.user_id AND uqs.group_id = $1
                WHERE gm.group_id = $1
                  AND (uqs.quiz_id IS NOT NULL OR 
                       EXISTS(SELECT 1 FROM user_quiz_scores WHERE user_id = u.id AND group_id = $1))
                GROUP BY u.id, u.username, u.first_name, u.last_name
                ORDER BY score DESC, correct DESC
            """, group_id)
            return [dict(row) for row in rows]
    
    async def get_universal_leaderboard(self, limit: int = 50) -> List[Dict]:
        """Get universal leaderboard across all groups"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.id, u.username, u.first_name, u.last_name, u.total_score as score
                FROM users u
                WHERE u.total_score > 0
                ORDER BY u.total_score DESC, u.correct_answers DESC
                LIMIT $1
            """, limit)
            return [dict(row) for row in rows]
    
    async def get_daily_universal_leaderboard(self, limit: int = 50) -> List[Dict]:
        """Get universal leaderboard based on last 24 hours scores only"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.id, u.username, u.first_name, u.last_name,
                       COALESCE(SUM(uqs.points), 0) as score,
                       COUNT(CASE WHEN uqs.points = 4 THEN 1 END) as correct,
                       COUNT(CASE WHEN uqs.points = -1 THEN 1 END) as wrong
                FROM users u
                JOIN user_quiz_scores uqs ON u.id = uqs.user_id
                WHERE uqs.answered_at >= NOW() - INTERVAL '24 hours'
                GROUP BY u.id, u.username, u.first_name, u.last_name
                HAVING COALESCE(SUM(uqs.points), 0) > 0
                ORDER BY score DESC, correct DESC
                LIMIT $1
            """, limit)
            return [dict(row) for row in rows]
    
    async def get_all_groups(self) -> List[Dict]:
        """Get all active groups"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM groups WHERE is_active = TRUE")
            return [dict(row) for row in rows]
    
    async def get_all_users(self) -> List[Dict]:
        """Get all users who have interacted with the bot"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, username, first_name, last_name FROM users")
            return [dict(row) for row in rows]
    
    async def get_bot_stats(self) -> Dict:
        """Get bot statistics"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            total_groups = await conn.fetchval("SELECT COUNT(*) FROM groups WHERE is_active = TRUE")
            total_quizzes = await conn.fetchval("SELECT COUNT(*) FROM quizzes")
            total_answers = await conn.fetchval("SELECT COUNT(*) FROM user_quiz_scores")
            
            return {
                "total_users": total_users,
                "total_groups": total_groups,
                "total_quizzes": total_quizzes,
                "total_answers": total_answers
            }
    
    async def fetchval(self, query: str, *args):
        """Execute query and return single value"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)
    
    async def execute(self, query: str, *args):
        """Execute query without return value"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def reset_weekly_leaderboard(self):
        """Reset all user scores and quiz scores for weekly leaderboard reset"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            # Reset all user total scores and stats
            await conn.execute("""
                UPDATE users SET 
                    total_score = 0,
                    correct_answers = 0,
                    wrong_answers = 0,
                    unattempted = 0,
                    updated_at = NOW()
            """)
            
            # Delete all user quiz scores
            await conn.execute("DELETE FROM user_quiz_scores")
            
            logger.info("Weekly leaderboard reset completed successfully")
    
    async def set_quiz_solution(self, quiz_id: int, solution_type: str, solution_content: str):
        """Set solution for a quiz"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO quiz_solutions (quiz_id, solution_type, solution_content, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (quiz_id) DO UPDATE SET
                    solution_type = $2,
                    solution_content = $3,
                    updated_at = NOW()
            """, quiz_id, solution_type, solution_content)
    
    async def get_quiz_solution(self, quiz_id: int) -> Optional[Dict]:
        """Get solution for a quiz"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT solution_type, solution_content, updated_at
                FROM quiz_solutions
                WHERE quiz_id = $1
            """, quiz_id)
            return dict(row) if row else None
    
    async def get_quiz_by_message_id(self, message_id: int, group_id: int) -> Optional[Dict]:
        """Get quiz by message ID from specific group"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, quiz_text, correct_option, options
                FROM quizzes
                WHERE message_id = $1 AND from_group_id = $2
            """, message_id, group_id)
            return dict(row) if row else None
    
    async def add_custom_reply(self, reply_type: str, message_type: str, content: Optional[str] = None, 
                              file_id: Optional[str] = None, caption: Optional[str] = None, added_by: Optional[int] = None) -> int:
        """Add custom reply to database"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            reply_id = await conn.fetchval("""
                INSERT INTO custom_replies (reply_type, message_type, content, file_id, caption, added_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, reply_type, message_type, content, file_id, caption, added_by)
            return reply_id
    
    async def get_custom_replies(self, reply_type: str) -> List[Dict]:
        """Get all custom replies of a specific type (positive/negative)"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, message_type, content, file_id, caption
                FROM custom_replies
                WHERE reply_type = $1
                ORDER BY created_at DESC
            """, reply_type)
            return [dict(row) for row in rows]
    
    async def remove_custom_reply(self, content: Optional[str] = None, file_id: Optional[str] = None) -> int:
        """Remove custom reply by content or file_id. Returns number of deleted rows"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            if content:
                result = await conn.execute("""
                    DELETE FROM custom_replies WHERE content = $1
                """, content)
            elif file_id:
                result = await conn.execute("""
                    DELETE FROM custom_replies WHERE file_id = $1
                """, file_id)
            else:
                return 0
            
            # Extract number of deleted rows from result string
            deleted_count = int(result.split()[-1]) if result else 0
            return deleted_count
    
    async def set_group_replies_status(self, group_id: int, enabled: bool):
        """Enable or disable replies for a group"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE groups SET replies_enabled = $2, updated_at = NOW()
                WHERE id = $1
            """, group_id, enabled)
    
    async def is_group_replies_enabled(self, group_id: int) -> bool:
        """Check if replies are enabled for a group"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT replies_enabled FROM groups WHERE id = $1
            """, group_id)
            return result if result is not None else True
    
    async def store_message_mapping(self, forwarded_message_id: int, user_id: int):
        """Store mapping of forwarded message to user"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO message_mapping (forwarded_message_id, user_id)
                VALUES ($1, $2)
                ON CONFLICT (forwarded_message_id) DO UPDATE SET user_id = $2
            """, forwarded_message_id, user_id)
    
    async def get_user_from_message(self, forwarded_message_id: int) -> Optional[int]:
        """Get user_id from forwarded message ID"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT user_id FROM message_mapping WHERE forwarded_message_id = $1
            """, forwarded_message_id)
            return result
    
    async def get_user_universal_rank(self, user_id: int) -> Optional[int]:
        """Get user's universal rank across all groups"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            # Get rank by counting users with higher total_score
            rank = await conn.fetchval("""
                SELECT COUNT(*) + 1 
                FROM users 
                WHERE total_score > (SELECT total_score FROM users WHERE id = $1)
            """, user_id)
            return rank
    
    async def get_user_group_scores(self, user_id: int) -> List[Dict]:
        """Get user's scores and ranks for all groups they participated in"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            # Get user's group-wise scores
            rows = await conn.fetch("""
                WITH user_group_scores AS (
                    SELECT 
                        g.id as group_id,
                        g.title as group_name,
                        COALESCE(SUM(uqs.points), 0) as score,
                        COUNT(CASE WHEN uqs.points = 4 THEN 1 END) as correct,
                        COUNT(CASE WHEN uqs.points = -1 THEN 1 END) as wrong,
                        COUNT(CASE WHEN uqs.points = 0 THEN 1 END) as unattempted
                    FROM groups g
                    JOIN user_quiz_scores uqs ON g.id = uqs.group_id
                    WHERE uqs.user_id = $1
                    GROUP BY g.id, g.title
                ),
                group_ranks AS (
                    SELECT 
                        uqs.group_id,
                        uqs.user_id,
                        RANK() OVER (PARTITION BY uqs.group_id ORDER BY SUM(uqs.points) DESC) as rank
                    FROM user_quiz_scores uqs
                    GROUP BY uqs.group_id, uqs.user_id
                )
                SELECT 
                    ugs.group_id,
                    ugs.group_name,
                    ugs.score,
                    ugs.correct,
                    ugs.wrong,
                    ugs.unattempted,
                    COALESCE(gr.rank, 0) as rank
                FROM user_group_scores ugs
                LEFT JOIN group_ranks gr ON ugs.group_id = gr.group_id AND gr.user_id = $1
                ORDER BY ugs.score DESC
            """, user_id)
            return [dict(row) for row in rows]
    
    async def set_group_language(self, group_id: int, language: str):
        """Set language preference for a group"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE groups SET language_preference = $2, updated_at = NOW()
                WHERE id = $1
            """, group_id, language.lower())
        # Invalidate cache
        self._invalidate_cache(f'group_language_{group_id}')
    
    async def get_group_language(self, group_id: int) -> str:
        """Get language preference for a group (cached to reduce DB queries)"""
        cache_key = f'group_language_{group_id}'
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT language_preference FROM groups WHERE id = $1
            """, group_id)
            language = result if result is not None else 'english'
            self._set_cache(cache_key, language, self._cache_ttl['group_language'])
            return language

    async def set_user_language(self, user_id: int, language: str):
        """Set language preference for a user (private chat)"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE users SET language_preference = $2, updated_at = NOW()
                WHERE id = $1
            """, user_id, language.lower())
        self._invalidate_cache(f'user_language_{user_id}')

    async def get_user_language(self, user_id: int) -> str:
        """Get language preference for a user (private chat), cached"""
        cache_key = f'user_language_{user_id}'
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT language_preference FROM users WHERE id = $1
            """, user_id)
            language = result if result is not None else 'english'
            self._set_cache(cache_key, language, self._cache_ttl['group_language'])
            return language
    
    async def add_clone_bot(self, bot_token: str, bot_id: int, bot_name: str, bot_username: str,
                            owner_id: int, owner_username: Optional[str], owner_name: Optional[str]) -> bool:
        """Register a new clone bot. Returns True if added, False if already exists."""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            existing = await conn.fetchval("SELECT bot_id FROM clone_bots WHERE bot_id = $1 OR owner_id = $2", bot_id, owner_id)
            if existing:
                return False
            await conn.execute("""
                INSERT INTO clone_bots (bot_token, bot_id, bot_name, bot_username, owner_id, owner_username, owner_name)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, bot_token, bot_id, bot_name, bot_username, owner_id, owner_username, owner_name)
            return True

    async def set_clone_pending(self, user_id: int):
        """Mark user as pending clone setup"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO clone_pending (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
                user_id
            )

    async def is_clone_pending(self, user_id: int) -> bool:
        """Check if user is in clone setup pending state"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchval("SELECT user_id FROM clone_pending WHERE user_id = $1", user_id)
            return row is not None

    async def clear_clone_pending(self, user_id: int):
        """Remove user from clone pending state"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM clone_pending WHERE user_id = $1", user_id)

    async def get_all_active_clone_bots(self) -> List[Dict]:
        """Get all active (not paused) clone bots"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM clone_bots WHERE is_active = TRUE AND is_paused = FALSE ORDER BY created_at
            """)
            return [dict(r) for r in rows]

    async def get_all_clone_bots(self) -> List[Dict]:
        """Get all clone bots including paused ones"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM clone_bots ORDER BY created_at")
            return [dict(r) for r in rows]

    async def get_clone_bot(self, bot_id: int) -> Optional[Dict]:
        """Get clone bot by its Telegram bot_id"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM clone_bots WHERE bot_id = $1", bot_id)
            return dict(row) if row else None

    async def get_clone_bot_by_owner(self, owner_id: int) -> Optional[Dict]:
        """Get clone bot by owner's user_id"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM clone_bots WHERE owner_id = $1", owner_id)
            return dict(row) if row else None

    async def pause_clone_bot(self, bot_id: int, reason: str):
        """Pause a clone bot"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE clone_bots SET is_paused = TRUE, pause_reason = $2 WHERE bot_id = $1
            """, bot_id, reason)

    async def resume_clone_bot(self, bot_id: int):
        """Resume a paused clone bot"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE clone_bots SET is_paused = FALSE, pause_reason = NULL WHERE bot_id = $1
            """, bot_id)

    async def get_clone_groups(self, clone_bot_id: int) -> List[Dict]:
        """Get all groups registered under a clone bot"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM groups WHERE clone_bot_id = $1 AND is_active = TRUE
            """, clone_bot_id)
            return [dict(r) for r in rows]

    async def get_clone_users(self, clone_bot_id: int) -> List[Dict]:
        """Get all users registered under a clone bot"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM users WHERE clone_bot_id = $1
            """, clone_bot_id)
            return [dict(r) for r in rows]

    async def get_clone_bot_stats(self, clone_bot_id: int) -> Dict:
        """Get stats for a clone bot"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            users_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE clone_bot_id = $1", clone_bot_id)
            groups_count = await conn.fetchval(
                "SELECT COUNT(*) FROM groups WHERE clone_bot_id = $1 AND is_active = TRUE AND type IN ('group','supergroup')", clone_bot_id)
            channels_count = await conn.fetchval(
                "SELECT COUNT(*) FROM groups WHERE clone_bot_id = $1 AND is_active = TRUE AND type = 'channel'", clone_bot_id)
            answers_count = await conn.fetchval("""
                SELECT COUNT(*) FROM user_quiz_scores uqs
                JOIN groups g ON uqs.group_id = g.id
                WHERE g.clone_bot_id = $1
            """, clone_bot_id)
            return {
                'users': users_count or 0,
                'groups': groups_count or 0,
                'channels': channels_count or 0,
                'total_answers': answers_count or 0
            }

    async def get_clone_leaderboard(self, clone_bot_id: int, limit: int = 10) -> List[Dict]:
        """Get leaderboard for a clone bot's audience"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.id, u.first_name, u.username, SUM(uqs.points) as total_score
                FROM user_quiz_scores uqs
                JOIN users u ON uqs.user_id = u.id
                JOIN groups g ON uqs.group_id = g.id
                WHERE g.clone_bot_id = $1
                GROUP BY u.id, u.first_name, u.username
                ORDER BY total_score DESC
                LIMIT $2
            """, clone_bot_id, limit)
            return [dict(r) for r in rows]

    async def add_poll_mapping(self, poll_id: str, quiz_id: int, group_id: int,
                                message_id: int, clone_bot_id: int, correct_option: int):
        """Store poll ID → quiz mapping for clone bots"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO poll_mappings (poll_id, quiz_id, group_id, message_id, clone_bot_id, correct_option)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (poll_id) DO NOTHING
            """, poll_id, quiz_id, group_id, message_id, clone_bot_id, correct_option)

    async def get_poll_mapping(self, poll_id: str) -> Optional[Dict]:
        """Get poll mapping by poll_id"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM poll_mappings WHERE poll_id = $1", poll_id)
            return dict(row) if row else None

    async def add_force_join_group(self, chat_id: int, chat_username: Optional[str] = None, 
                                   chat_title: Optional[str] = None, chat_type: Optional[str] = None,
                                   invite_link: Optional[str] = None, added_by: Optional[int] = None) -> bool:
        """Add a group/channel to force join list. Returns True if added, False if limit reached for new groups"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            # Check if this chat_id already exists
            existing = await conn.fetchval("SELECT chat_id FROM force_join_groups WHERE chat_id = $1", chat_id)
            
            # If it doesn't exist, check if we've reached the limit
            if not existing:
                count = await conn.fetchval("SELECT COUNT(*) FROM force_join_groups")
                if count >= 5:
                    return False
            
            # Add or update the group
            await conn.execute("""
                INSERT INTO force_join_groups (chat_id, chat_username, chat_title, chat_type, invite_link, added_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (chat_id) DO UPDATE SET
                    chat_username = $2,
                    chat_title = $3,
                    chat_type = $4,
                    invite_link = $5
            """, chat_id, chat_username, chat_title, chat_type, invite_link, added_by)
            self._invalidate_cache('force_join_groups')  # Invalidate cache
            return True
    
    async def remove_force_join_group(self, chat_id: int) -> bool:
        """Remove a group/channel from force join list. Returns True if removed, False if not found"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM force_join_groups WHERE chat_id = $1", chat_id)
            deleted_count = int(result.split()[-1]) if result else 0
            if deleted_count > 0:
                self._invalidate_cache('force_join_groups')  # Invalidate cache
            return deleted_count > 0
    
    async def get_force_join_groups(self) -> List[Dict]:
        """Get all force join groups/channels (cached to reduce DB queries)"""
        cache_key = 'force_join_groups'
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached
        
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM force_join_groups ORDER BY created_at")
            groups = [dict(row) for row in rows]
            self._set_cache(cache_key, groups, self._cache_ttl['force_join_groups'])
            return groups
    
    async def get_force_join_count(self) -> int:
        """Get count of force join groups"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM force_join_groups")
    
    async def get_user_daily_wrong_answers(self, user_id: int, date: datetime) -> List[Dict]:
        """Get all unique wrong answers for a user on a specific date (Indian timezone)"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        
        # Calculate start and end of the day in UTC (from IST)
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        
        # Create start and end of day in IST
        day_start_ist = ist.localize(datetime(date.year, date.month, date.day, 0, 0, 0))
        day_end_ist = ist.localize(datetime(date.year, date.month, date.day, 23, 59, 59))
        
        # Convert to naive UTC for asyncpg compatibility
        day_start_utc = day_start_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        day_end_utc = day_end_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (q.id) 
                    q.id as quiz_id,
                    q.quiz_text,
                    q.options,
                    q.correct_option,
                    uqs.selected_option,
                    uqs.answered_at
                FROM user_quiz_scores uqs
                JOIN quizzes q ON uqs.quiz_id = q.id
                WHERE uqs.user_id = $1 
                  AND uqs.points = -1
                  AND uqs.answered_at >= $2
                  AND uqs.answered_at <= $3
                ORDER BY q.id, uqs.answered_at DESC
            """, user_id, day_start_utc, day_end_utc)
            return [dict(row) for row in rows]
    
    async def get_users_with_wrong_answers_today(self, date: datetime) -> List[int]:
        """Get list of user IDs who have wrong answers today"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        
        # Create start and end of day in IST
        day_start_ist = ist.localize(datetime(date.year, date.month, date.day, 0, 0, 0))
        day_end_ist = ist.localize(datetime(date.year, date.month, date.day, 23, 59, 59))
        
        # Convert to naive UTC for asyncpg compatibility
        day_start_utc = day_start_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        day_end_utc = day_end_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT user_id
                FROM user_quiz_scores
                WHERE points = -1
                  AND answered_at >= $1
                  AND answered_at <= $2
            """, day_start_utc, day_end_utc)
            return [row['user_id'] for row in rows]
    
    async def store_sent_message(self, original_message_id: int, original_chat_id: int, 
                                  sent_message_id: int, sent_chat_id: int, sent_by: int):
        """Store a sent message mapping for later deletion"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sent_messages (original_message_id, original_chat_id, sent_message_id, sent_chat_id, sent_by)
                VALUES ($1, $2, $3, $4, $5)
            """, original_message_id, original_chat_id, sent_message_id, sent_chat_id, sent_by)
    
    async def get_sent_messages(self, original_message_id: int, original_chat_id: int) -> List[Dict]:
        """Get all sent messages for a given original message"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT sent_message_id, sent_chat_id
                FROM sent_messages
                WHERE original_message_id = $1 AND original_chat_id = $2
            """, original_message_id, original_chat_id)
            return [dict(row) for row in rows]
    
    async def delete_sent_message_records(self, original_message_id: int, original_chat_id: int):
        """Delete all sent message records for a given original message"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM sent_messages
                WHERE original_message_id = $1 AND original_chat_id = $2
            """, original_message_id, original_chat_id)

# Global database instance
db = Database()
