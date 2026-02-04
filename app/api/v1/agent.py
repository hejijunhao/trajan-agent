"""CLI Agent API endpoint for conversational project queries."""

import uuid as uuid_pkg

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_with_rls
from app.domain import product_ops
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
    db: AsyncSession = Depends(get_db_with_rls),
) -> ChatResponse:
    """Chat with the CLI agent about a project.

    RLS ensures the user can only access products they have permission for.
    Full message history is sent per request (stateless backend).
    """
    # RLS will return None for inaccessible products
    product = await product_ops.get(db, data.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or access denied")

    service = CLIAgentService()
    try:
        response_text = await service.chat(
            db,
            data.product_id,
            [m.model_dump() for m in data.messages],
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
