"""CLI Agent API endpoint for conversational project queries."""

import uuid as uuid_pkg

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db_with_rls,
    require_product_subscription,
)
from app.domain import preferences_ops
from app.models.user import User
from app.services.agent import CLIAgentService

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
# Endpoint
# ─────────────────────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def agent_chat(
    data: ChatRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> ChatResponse:
    """Chat with the CLI agent about a project.

    RLS ensures the user can only access products they have permission for.
    Full message history is sent per request (stateless backend).
    """
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
