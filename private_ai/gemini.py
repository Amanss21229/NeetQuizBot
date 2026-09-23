"""Gemini API provider for Private AI."""

from __future__ import annotations

from typing import Sequence

from google import genai
from google.genai import types

from .chat import ChatMessage


class GeminiProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
    ):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        system_prompt: str,
    ) -> str:
        contents = [
            types.Content(
                role="user" if message.role == "user" else "model",
                parts=[
                    types.Part(
                        text=message.content
                    )
                ],
            )
            for message in messages
        ]

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1200,
            ),
        )

        if not response.text:
            raise RuntimeError(
                "Gemini returned an empty response"
            )

        return response.text.strip()


__all__ = ["GeminiProvider"]
