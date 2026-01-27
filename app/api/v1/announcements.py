"""Announcements API endpoints for system-wide banners."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.domain import announcement_ops

router = APIRouter(prefix="/announcements", tags=["announcements"])


# ─────────────────────────────────────────────────────────────────────────────
# Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class AnnouncementResponse(BaseModel):
    """Single announcement for display."""

    id: str
    title: str | None
    message: str
    link_url: str | None
    link_text: str | None
    variant: str
    is_dismissible: bool
    dismiss_key: str | None


class ActiveAnnouncementsResponse(BaseModel):
    """Response containing all active announcements."""

    announcements: list[AnnouncementResponse]


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/active", response_model=ActiveAnnouncementsResponse)
async def get_active_announcements(
    db: DbSession,
    _current_user: CurrentUser,  # Require authentication
) -> ActiveAnnouncementsResponse:
    """Get all currently active announcements.

    Returns announcements that are:
    - Marked as active
    - Within their scheduled time window (if set)

    Ordered by priority (error > warning > info) then by creation date.
    """
    announcements = await announcement_ops.get_active(db)

    return ActiveAnnouncementsResponse(
        announcements=[
            AnnouncementResponse(
                id=str(a.id),
                title=a.title,
                message=a.message,
                link_url=a.link_url,
                link_text=a.link_text,
                variant=a.variant.value if hasattr(a.variant, "value") else str(a.variant),
                is_dismissible=a.is_dismissible,
                dismiss_key=a.dismiss_key,
            )
            for a in announcements
        ]
    )
