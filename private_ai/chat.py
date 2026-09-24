"""Provider-independent chat orchestration for Private AI.

The actual model provider is deliberately not hard-coded in Phase 2. The next
integration phase can plug in a free-tier provider without changing the bot's
credit/memory/safety interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .credits import CreditService
from .memory import MemoryService
from .prompts import build_system_prompt
from .safety import SafetyService
from .tasks import TaskService


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatResult:
    text: str
    credits_used: int = 0
    safety_category: str = "normal"


class AIProvider(Protocol):
    async def generate(self, messages: Sequence[ChatMessage], system_prompt: str) -> str:
        """Generate one assistant response."""


class PrivateAI:
    """Coordinates safety, memory, provider call and credit accounting."""

    def __init__(self, db, provider: AIProvider):
        self.db = db
        self.provider = provider
        self.credits = CreditService(db)
        self.memory = MemoryService(db)
        self.safety = SafetyService()
        self.tasks = TaskService(db)

    async def prepare_user(self, user_id: int) -> bool:
        """Initialize profile and one-time credits for a user."""
        await self.memory.ensure_profile(user_id)
        return await self.credits.initialize_for_user(user_id)

    async def respond(self, user_id: int, user_text: str, history: Sequence[ChatMessage] = ()) -> ChatResult:
        safety = self.safety.classify(user_text)
        if not safety.allowed:
            return ChatResult(
                text=self._safe_response(safety.category),
                credits_used=0,
                safety_category=safety.category,
            )

        context = await self.memory.build_context(user_id)
        system_prompt = build_system_prompt(
            memory_context=context,
            safety_constraints=self.safety.system_constraints(),
        )

        messages = list(history) + [ChatMessage(role="user", content=user_text)]
        text = await self.provider.generate(messages, system_prompt)
        return ChatResult(text=text, credits_used=0, safety_category="normal")

    @staticmethod
    def _safe_response(category: str) -> str:
        if category == "high_risk":
            return ("I’m here with you, but I can’t provide instructions for harming yourself. "
                    "Please tell a trusted adult or someone you trust right now and stay with them.")
        if category == "explicit_sexual":
            return ("I can help with factual, age-appropriate health or biology questions, "
                    "but I can’t generate explicit sexual content.")
        return "I can help with that in a safe, age-appropriate way."


__all__ = ["PrivateAI", "AIProvider", "ChatMessage", "ChatResult"]
