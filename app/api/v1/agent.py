"""CLI Agent API endpoint for conversational project queries."""

import json
import logging
import uuid as uuid_pkg
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    check_product_viewer_access,
    get_current_user,
    get_db_with_rls,
    require_product_subscription,
)
from app.domain import preferences_ops
from app.models.user import User
from app.services.agent import CLIAgentService
from app.services.agent.context import ContextBuilder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# ─────────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────


class ChatMessagePayload(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    product_id: uuid_pkg.UUID
    messages: list[ChatMessagePayload]


class ChatResponse(BaseModel):
    response: str
    product_id: str


# ─────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def agent_chat(
    data: ChatRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> ChatResponse:
    """Chat with the CLI agent about a project.

    Full message history is sent per request (stateless backend).
    """
    await check_product_viewer_access(db, data.product_id, _current_user.id)
    await require_product_subscription(db, data.product_id)

    # Fetch user's GitHub token for live repo context
    prefs = await preferences_ops.get_by_user_id(db, _current_user.id)
    github_token = preferences_ops.get_decrypted_token(prefs) if prefs else None

    service = CLIAgentService()
    try:
        response_text = await service.chat(
            db,
            data.product_id,
            [m.model_dump() for m in data.messages],
            github_token=github_token,
        )
    except anthropic.RateLimitError as err:
        raise HTTPException(
            status_code=429,
            detail="AI rate limit reached. Please try again shortly.",
        ) from err
    except anthropic.APIError as err:
        raise HTTPException(
            status_code=503,
            detail="AI service temporarily unavailable.",
        ) from err

    return ChatResponse(
        response=response_text,
        product_id=str(data.product_id),
    )


@router.post("/chat/stream")
async def agent_chat_stream(
    data: ChatRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> StreamingResponse:
    """Stream a chat response as Server-Sent Events."""
    await check_product_viewer_access(db, data.product_id, _current_user.id)
    await require_product_subscription(db, data.product_id)

    prefs = await preferences_ops.get_by_user_id(db, _current_user.id)
    github_token = preferences_ops.get_decrypted_token(prefs) if prefs else None

    service = CLIAgentService()

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for delta in service.chat_stream(
                db,
                data.product_id,
                [m.model_dump() for m in data.messages],
                github_token=github_token,
            ):
                yield f"data: {json.dumps({'text': delta})}\n\n"
            yield "data: [DONE]\n\n"
        except anthropic.RateLimitError:
            yield f"data: {json.dumps({'error': 'AI rate limit reached. Please try again shortly.'})}\n\n"
        except anthropic.APIError:
            yield f"data: {json.dumps({'error': 'AI service temporarily unavailable.'})}\n\n"
        except Exception:
            logger.exception("Unexpected error in agent stream")
            yield f"data: {json.dumps({'error': 'An unexpected error occurred.'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/context-summary")
async def agent_context_summary(
    product_id: uuid_pkg.UUID = Query(...),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Return a structured summary of what the agent can access for a product."""
    await check_product_viewer_access(db, product_id, _current_user.id)

    prefs = await preferences_ops.get_by_user_id(db, _current_user.id)
    github_token = preferences_ops.get_decrypted_token(prefs) if prefs else None

    builder = ContextBuilder()
    return await builder.build_summary(db, product_id, github_token=github_token)
