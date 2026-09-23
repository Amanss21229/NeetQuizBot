"""Persistent reminder/task service built on the existing scheduler."""

from __future__ import annotations

from datetime import datetime


class TaskService:
    def __init__(self, db):
        self.db = db

    async def create(
        self,
        user_id: int,
        task_text: str,
        schedule_type: str,
        schedule_data: dict,
        timezone_name: str = "Asia/Kolkata",
        next_run_at: datetime | None = None,
    ) -> int:
        return await self.db.create_ai_task(
            user_id=user_id,
            task_text=task_text,
            schedule_type=schedule_type,
            schedule_data=schedule_data,
            timezone_name=timezone_name,
            next_run_at=next_run_at,
        )

    async def list_active(self, user_id: int | None = None) -> list[dict]:
        return await self.db.get_active_ai_tasks(user_id)

    async def cancel(self, user_id: int, task_id: int) -> bool:
        return await self.db.deactivate_ai_task(task_id, user_id)

    async def update_next_run(self, task_id: int, next_run_at: datetime | None, active: bool = True) -> None:
        await self.db.update_ai_task_next_run(task_id, next_run_at, active)


__all__ = ["TaskService"]
