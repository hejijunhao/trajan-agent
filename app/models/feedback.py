"""Feedback model for user bug reports and feature requests."""

import uuid as uuid_pkg
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin, UUIDMixin


class FeedbackType(str, Enum):
    """Type of feedback submission."""

    BUG = "bug"
    FEATURE = "feature"
    OTHER = "other"


class FeedbackStatus(str, Enum):
    """Status of feedback in review pipeline."""

    NEW = "new"
    REVIEWED = "reviewed"
    PLANNED = "planned"
    CLOSED = "closed"


class FeedbackSeverity(str, Enum):
    """Severity level for bug reports."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Feedback(UUIDMixin, TimestampMixin, SQLModel, table=True):
    """User feedback submission (bug report or feature request)."""

    __tablename__ = "feedback"

    # User who submitted
    user_id: uuid_pkg.UUID = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
    )

    # Type & Categories
    type: str = Field(max_length=20, nullable=False)
    tags: list[str] = Field(default=[], sa_column=Column(JSONB, server_default="[]"))
    severity: str | None = Field(default=None, max_length=20)

    # User Input
    title: str = Field(max_length=200, nullable=False)
    description: str = Field(nullable=False)

    # AI Interpretation
    ai_summary: str | None = Field(default=None)
    ai_processed_at: datetime | None = Field(  # type: ignore[call-overload]
        default=None, sa_type=DateTime(timezone=True)
    )

    # Context
    page_url: str | None = Field(default=None, max_length=500)
    user_agent: str | None = Field(default=None, max_length=500)

    # Status Tracking
    status: str = Field(default="new", max_length=20)
    admin_notes: str | None = Field(default=None)


class FeedbackCreate(SQLModel):
    """Schema for creating feedback."""

    type: str
    tags: list[str] = []
    severity: str | None = None
    title: str
    description: str
    page_url: str | None = None
    user_agent: str | None = None


class FeedbackRead(SQLModel):
    """Schema for reading feedback."""

    id: uuid_pkg.UUID
    type: str
    tags: list[str]
    severity: str | None
    title: str
    description: str
    ai_summary: str | None
    page_url: str | None
    status: str
    created_at: datetime
