"""Private AI profile and long-term memory helpers."""

from __future__ import annotations

from typing import Any


SENSITIVE_PROFILE_FIELDS = {"age", "gender", "city"}


class MemoryService:
    """Keeps durable personalization small and explicit.

    Full chat history is intentionally not duplicated into PostgreSQL here; the
    Activity GC is the archival layer planned for the integration phase.
    """

    def __init__(self, db):
        self.db = db

    async def ensure_profile(self, user_id: int) -> dict:
        return await self.db.create_ai_profile(user_id)

    async def get_profile(self, user_id: int) -> dict | None:
        return await self.db.get_ai_profile(user_id)

    async def update_profile(self, user_id: int, **fields: Any) -> None:
        allowed = {
            "preferred_name", "age", "city", "gender", "study_class",
            "exam_target", "goals", "preferences", "memory_summary",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unsupported profile fields: {sorted(unknown)}")
        await self.db.update_ai_profile(user_id, **fields)

    async def build_context(self, user_id: int) -> str:
        profile = await self.db.get_ai_profile(user_id)
        if not profile:
            return "No saved personalization yet."

        labels = {
            "preferred_name": "Preferred name",
            "study_class": "Study class",
            "exam_target": "Exam target",
            "goals": "Goals",
            "preferences": "Preferences",
            "memory_summary": "Long-term memory",
        }

        parts = []
        for key, label in labels.items():
            value = profile.get(key)
            if value:
                parts.append(f"{label}: {value}")

        # Sensitive fields are available only when explicitly supplied by the user.
        for key in ("age", "city", "gender"):
            value = profile.get(key)
            if value is not None:
                parts.append(f"{key.replace('_', ' ').title()}: {value}")

        return "\n".join(parts) if parts else "No saved personalization yet."


__all__ = ["MemoryService", "SENSITIVE_PROFILE_FIELDS"]
