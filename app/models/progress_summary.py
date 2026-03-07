"""Progress summary model for AI-generated development narratives."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


class ProgressSummary(SQLModel, table=True):
    """
    AI-generated narrative summaries for development progress.

    Stores one summary per (product, period) combination using an upsert pattern.
    When a user requests a new summary, the existing one is replaced.

    This is a shared cache (not user-scoped) because:
    1. Summaries are computed from the same commit data for all users
    2. Avoids regenerating identical summaries for different users
    """

    __tablename__ = "progress_summary"
    __table_args__ = (
        Index(
            "ix_progress_summary_product_period",
            "product_id",
            "period",
            unique=True,
        ),
    )

    id: uuid_pkg.UUID = Field(
        default_factory=uuid_pkg.uuid4,
        primary_key=True,
        nullable=False,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )

    product_id: uuid_pkg.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    period: str = Field(
        max_length=10,
        nullable=False,
        description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d",
    )

    summary_text: str = Field(
        nullable=False,
        description="AI-generated narrative summary (2-4 sentences)",
    )

    # Stats snapshot at time of generation (for context/debugging)
    total_commits: int = Field(default=0, nullable=False)
    total_contributors: int = Field(default=0, nullable=False)
    total_additions: int = Field(default=0, nullable=False)
    total_deletions: int = Field(default=0, nullable=False)

    # Per-contributor AI summaries for email digest progress review
    contributor_summaries: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(
            JSONB,
            nullable=True,
            comment=(
                "Per-contributor AI summaries. "
                "Array of {name, summary_text, commit_count, additions, deletions, "
                "commit_refs: [{sha, branch}]}"
            ),
        ),
    )

    # Activity tracking for auto-progress smart-skip logic
    last_activity_at: datetime | None = Field(  # type: ignore[call-overload]
        default=None,
        nullable=True,
        sa_type=DateTime(timezone=True),
        description="Timestamp of the newest commit seen during last generation/check",
    )

    generated_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
        description="When this summary was generated",
    )

    created_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
    )

    updated_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
    )
