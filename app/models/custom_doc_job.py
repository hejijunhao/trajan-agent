"""CustomDocJob model for persistent job storage.

Replaces in-memory job store for multi-worker compatibility.
Jobs are stored in the database with automatic TTL cleanup.
"""

import uuid as uuid_pkg
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import DateTime, Index, text
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin, UUIDMixin


class JobStatus(str, Enum):
    """Status of a custom document generation job."""

    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CustomDocJob(UUIDMixin, TimestampMixin, SQLModel, table=True):
    """Persistent storage for custom document generation jobs.

    Replaces in-memory singleton for multi-worker deployments.
    Jobs older than TTL are cleaned up by a background task.
    """

    __tablename__ = "custom_doc_jobs"
    __table_args__ = (
        Index("ix_custom_doc_jobs_user_product", "user_id", "product_id"),
        Index("ix_custom_doc_jobs_status_created", "status", "created_at"),
    )

    # Job ownership
    product_id: uuid_pkg.UUID = Field(
        nullable=False,
        index=True,
    )
    user_id: uuid_pkg.UUID = Field(
        nullable=False,
        index=True,
    )

    # Job state
    status: str = Field(
        default=JobStatus.GENERATING.value,
        max_length=20,
        index=True,
    )
    progress: str = Field(
        default="Analyzing codebase...",
        max_length=100,
    )

    # Result data (null until completed)
    content: str | None = Field(default=None)
    suggested_title: str | None = Field(default=None, max_length=500)
    error: str | None = Field(default=None, max_length=2000)

    # Expiration
    expires_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now() + interval '1 hour'")},
    )
