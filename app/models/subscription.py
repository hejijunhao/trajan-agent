"""Subscription model - organization billing and plan management."""

import uuid as uuid_pkg
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class PlanTier(str, Enum):
    """Available subscription plan tiers."""

    OBSERVER = "observer"  # Free - $0
    FOUNDATIONS = "foundations"  # $149/mo
    CORE = "core"  # $299/mo
    AUTONOMOUS = "autonomous"  # $499/mo


class SubscriptionStatus(str, Enum):
    """Subscription lifecycle states."""

    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    # Note: No TRIALING - we don't do free trials


class Subscription(SQLModel, table=True):
    """
    Subscription model - tracks an organization's billing status.

    Each organization has exactly one subscription. Free tier organizations
    get a subscription with plan_tier=OBSERVER.

    Supports two assignment modes:
    1. Stripe-managed: Payment through Stripe, subscription synced via webhooks
    2. Manually assigned: Admin sets plan directly (for founders, beta testers)
    """

    __tablename__ = "subscriptions"

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
            unique=True,
            index=True,
        ),
    )

    # Plan info
    plan_tier: str = Field(
        default=PlanTier.OBSERVER.value,
        sa_column=Column(
            String(20),
            nullable=False,
            server_default=PlanTier.OBSERVER.value,
        ),
    )
    status: str = Field(
        default=SubscriptionStatus.ACTIVE.value,
        sa_column=Column(
            String(20),
            nullable=False,
            server_default=SubscriptionStatus.ACTIVE.value,
        ),
    )

    # Repository limits (base from plan, metered billing for overages on paid plans)
    base_repo_limit: int = Field(
        default=1,
        nullable=False,
        sa_column_kwargs={"server_default": text("1")},
    )

    # Billing period
    current_period_start: datetime | None = Field(default=None, nullable=True)
    current_period_end: datetime | None = Field(default=None, nullable=True)
    cancel_at_period_end: bool = Field(
        default=False,
        nullable=False,
        sa_column_kwargs={"server_default": text("false")},
    )
    canceled_at: datetime | None = Field(default=None, nullable=True)

    # Stripe references (nullable for manually assigned subscriptions)
    stripe_customer_id: str | None = Field(
        default=None, max_length=255, nullable=True, index=True
    )
    stripe_subscription_id: str | None = Field(
        default=None, max_length=255, nullable=True
    )
    stripe_metered_item_id: str | None = Field(
        default=None,
        max_length=255,
        nullable=True,
        sa_column_kwargs={"comment": "Stripe subscription item ID for overage billing"},
    )

    # Referral tracking
    referral_credit_cents: int = Field(
        default=0,
        nullable=False,
        sa_column_kwargs={
            "server_default": text("0"),
            "comment": "Accumulated referral credits in cents",
        },
    )

    # Admin override fields - for manual plan assignment without Stripe
    is_manually_assigned: bool = Field(
        default=False,
        nullable=False,
        sa_column_kwargs={
            "server_default": text("false"),
            "comment": "True if plan was assigned by admin, bypassing Stripe",
        },
    )
    manually_assigned_by: uuid_pkg.UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    manually_assigned_at: datetime | None = Field(default=None, nullable=True)
    manual_assignment_note: str | None = Field(
        default=None,
        max_length=500,
        nullable=True,
        sa_column_kwargs={"comment": "Reason for manual assignment, e.g., 'Founder account'"},
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"server_default": text("now()")},
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": text("now()")},
    )

    # Relationships
    organization: Optional["Organization"] = Relationship(back_populates="subscription")
    assigned_by: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Subscription.manually_assigned_by]"}
    )


# Request/Response schemas
class SubscriptionUpdate(SQLModel):
    """Schema for admin subscription update."""

    plan_tier: str
    note: str | None = None
