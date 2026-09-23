"""Credit business logic for the private AI system."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional
import random


# Weighted daily bonus. Values are intentionally bounded to 10-19.
BONUS_WEIGHTS = {
    10: 20,
    11: 15,
    12: 15,
    13: 12,
    14: 10,
    15: 8,
    16: 7,
    17: 5,
    18: 5,
    19: 3,
}


class CreditService:
    """High-level credit rules backed by the existing Database methods."""

    def __init__(self, db):
        self.db = db

    async def initialize_for_user(self, user_id: int) -> bool:
        """Give the one-time 30-credit AI welcome gift if not initialized."""
        return await self.db.initialize_ai_credits(user_id, 30)

    async def balance(self, user_id: int) -> int:
        row = await self.db.get_ai_credits(user_id)
        return int(row["balance"]) if row else 0

    async def consume(self, user_id: int, amount: int = 1, reason: str = "AI_USAGE") -> Optional[dict]:
        if amount <= 0:
            raise ValueError("Credit amount must be greater than zero")
        return await self.db.consume_ai_credit(
            user_id,
            amount,
            transaction_type=reason,
            metadata={"source": "private_ai"},
        )

    async def add(self, user_id: int, amount: int, reason: str, admin_id: int | None = None) -> Optional[dict]:
        return await self.db.add_ai_credits(
            user_id,
            amount,
            transaction_type=reason,
            admin_id=admin_id,
            metadata={"source": "private_ai"},
        )

    async def daily_bonus_amount(self) -> int:
        return random.choices(
            list(BONUS_WEIGHTS.keys()),
            weights=list(BONUS_WEIGHTS.values()),
            k=1,
        )[0]

    async def can_claim_bonus(self, user_id: int, now: datetime | None = None) -> tuple[bool, Optional[datetime]]:
        last = await self.db.get_last_bonus_at(user_id)
        if last is None:
            return True, None

        now = now or datetime.now(timezone.utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = now - last
        return elapsed.total_seconds() >= 24 * 60 * 60, last

        async def claim_daily_bonus(
    self,
    user_id: int
) -> tuple[Optional[int], Optional[datetime]]:

    amount = await self.daily_bonus_amount()

    result = await self.db.claim_ai_daily_bonus(
        user_id,
        amount
    )

    if result is None:
        last = await self.db.get_last_bonus_at(user_id)

        if last is None:
            return None, None

        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        next_time = last + timedelta(hours=24)

        return None, next_time

    last_bonus = result["last_bonus_at"]

    if last_bonus.tzinfo is None:
        last_bonus = last_bonus.replace(
            tzinfo=timezone.utc
        )

    next_time = last_bonus + timedelta(hours=24)

    return amount, next_time

__all__ = ["CreditService", "BONUS_WEIGHTS"]
