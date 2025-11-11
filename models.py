import asyncio
import asyncpg
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Union

# Setup logger
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
    
    async def init_pool(self):
        """Initialize database connection pool"""
        self.pool = await asyncpg.create_pool(
            os.environ.get("DATABASE_URL"),
            min_size=1,
            max_size=10
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

    
    async def add_user(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None):
        """Add or update user in database"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (id, username, first_name, last_name, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    username = $2,
                    first_name = $3,
                    last_name = $4,
                    updated_at = NOW()
            """, user_id, username, first_name, last_name)
    
    async def add_group(self, group_id: int, title: str, group_type: str):
        """Add or update group in database"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO groups (id, title, type, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    title = $2,
                    type = $3,
                    updated_at = NOW()
            """, group_id, title, group_type)
    
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
    
    async def get_all_groups(self) -> List[Dict]:
        """Get all active groups"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM groups WHERE is_active = TRUE")
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
    
    async def set_group_language(self, group_id: int, language: str):
        """Set language preference for a group"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE groups SET language_preference = $2, updated_at = NOW()
                WHERE id = $1
            """, group_id, language.lower())
    
    async def get_group_language(self, group_id: int) -> str:
        """Get language preference for a group"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT language_preference FROM groups WHERE id = $1
            """, group_id)
            return result if result is not None else 'english'

# Global database instance
db = Database()
