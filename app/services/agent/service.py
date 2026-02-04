"""CLI Agent service for conversational project queries."""

import uuid as uuid_pkg
from typing import Literal, cast

import anthropic
from anthropic.types import MessageParam
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .context import ContextBuilder
from .prompts import AGENT_SYSTEM_PROMPT


class CLIAgentService:
    """Conversational agent for project queries.

    Unlike BaseInterpreter (single-shot), this handles multi-turn
    conversations by accepting full message history.
    """

    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.anthropic_api_key
        self._client: anthropic.AsyncAnthropic | None = None
        self._context_builder = ContextBuilder()

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        """Lazy-loaded async client (same pattern as BaseInterpreter)."""
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def chat(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        messages: list[dict[str, str]],
    ) -> str:
        """Send a conversational message with product context.

        Args:
            db: Database session with RLS context set.
            product_id: The product to query about.
            messages: Full conversation history [{role, content}, ...].

        Returns:
            The assistant's response text.
        """
        context = await self._context_builder.build(db, product_id)
        system = f"{AGENT_SYSTEM_PROMPT}\n\n---\n\n{context}"

        typed_messages: list[MessageParam] = [
            {
                "role": cast(Literal["user", "assistant"], m["role"]),
                "content": m["content"],
            }
            for m in messages
        ]

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=typed_messages,
        )

        first_block = response.content[0]
        return first_block.text if hasattr(first_block, "text") else str(first_block)
