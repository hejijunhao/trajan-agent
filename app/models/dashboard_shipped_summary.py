"""Dashboard shipped summary model for caching AI-generated "What Shipped" data."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class DashboardShippedSummary(SQLModel, table=True):
    """
    AI-generated "What Shipped" summaries for the Dashboard Progress section.

    Stores per-product shipped items (features, fixes, improvements) for a given
    time period. This is a shared cache (not user-scoped) because summaries are
    computed from the same commit data for all users.

    The items field stores a JSON array of shipped items:
    [
        {"description": "Added OAuth login", "category": "feature"},
        {"description": "Fixed Safari redirect bug", "category": "fix"},
    ]
    """

    __tablename__ = "dashboard_shipped_summary"
    __table_args__ = (
        Index(
            "ix_dashboard_shipped_summary_product_period",
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
        foreign_key="products.id",
        nullable=False,
        index=True,
        description="Product this summary belongs to",
    )

    period: str = Field(
        max_length=10,
        nullable=False,
        description="Time period: 7d, 14d, 30d",
    )

    # JSON array of shipped items
    items: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(
            JSONB,
            nullable=False,
            server_default=text("'[]'::jsonb"),
            comment="Array of shipped items: [{description, category}]",
        ),
    )

    # Whether there were significant changes
    has_significant_changes: bool = Field(
        default=True,
        nullable=False,
        description="Whether this product had meaningful changes in the period",
    )

    # Stats snapshot at time of generation
    total_commits: int = Field(default=0, nullable=False)
    total_additions: int = Field(default=0, nullable=False)
    total_deletions: int = Field(default=0, nullable=False)

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
