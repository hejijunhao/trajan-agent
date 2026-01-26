"""Billing models - usage tracking, events, and referrals."""

import uuid as uuid_pkg
from datetime import UTC, date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class BillingEventType(str, Enum):
    """Types of billing events for audit logging."""

    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    SUBSCRIPTION_CANCELED = "subscription.canceled"
    PLAN_CHANGED = "plan.changed"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    OVERAGE_BILLED = "overage.billed"
    REFERRAL_CREDIT_APPLIED = "referral.credit_applied"
    REFERRAL_EARNED = "referral.earned"
    MANUAL_ASSIGNMENT = "manual.assignment"


class UsageSnapshot(SQLModel, table=True):
    """
    Monthly usage snapshot for billing and analytics.

    Captured at the end of each billing period to track historical usage.
    """

    __tablename__ = "usage_snapshots"
    __table_args__ = (Index("ix_usage_snapshots_period", "organization_id", "period_start"),)

    id: uuid_pkg.UUID = Field(
        default_factory=uuid_pkg.uuid4,
        primary_key=True,
        nullable=False,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )
    organization_id: uuid_pkg.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    # Period
    period_start: date = Field(
        sa_column=Column(Date, nullable=False),
    )
    period_end: date = Field(
        sa_column=Column(Date, nullable=False),
    )

    # Counts (snapshot at period end)
    repository_count: int = Field(default=0, nullable=False)
    product_count: int = Field(default=0, nullable=False)
    analysis_count: int = Field(
        default=0,
        nullable=False,
        sa_column_kwargs={"comment": "Number of AI analyses run this period"},
    )
    member_count: int = Field(
        default=0,
        nullable=False,
        sa_column_kwargs={"comment": "Team size (for analytics, not billing)"},
    )

    # Computed at snapshot time
    plan_tier: str = Field(
        max_length=20,
        nullable=False,
        sa_column_kwargs={"comment": "Plan tier at time of snapshot"},
    )
    repo_limit: int = Field(
        nullable=False,
        sa_column_kwargs={"comment": "Base limit at time of snapshot"},
    )
    overage_repos: int = Field(
        default=0,
        nullable=False,
        sa_column_kwargs={"comment": "Repos over base limit (billable on paid plans)"},
    )

    created_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
    )

    # Relationships
    organization: Optional["Organization"] = Relationship()


class BillingEvent(SQLModel, table=True):
    """
    Billing event audit log.

    Tracks all billing-related changes for audit and debugging.
    """

    __tablename__ = "billing_events"

    id: uuid_pkg.UUID = Field(
        default_factory=uuid_pkg.uuid4,
        primary_key=True,
        nullable=False,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )
    organization_id: uuid_pkg.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    event_type: str = Field(
        sa_column=Column(String(50), nullable=False, index=True),
    )
    description: str | None = Field(default=None, max_length=500, nullable=True)

    # Change tracking
    previous_value: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    new_value: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )

    # Stripe reference (if applicable)
    stripe_event_id: str | None = Field(
        default=None,
        max_length=255,
        nullable=True,
        index=True,
    )

    # Actor (which user triggered this, if applicable)
    actor_user_id: uuid_pkg.UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    created_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
    )

    # Relationships
    organization: Optional["Organization"] = Relationship()
    actor: Optional["User"] = Relationship()
