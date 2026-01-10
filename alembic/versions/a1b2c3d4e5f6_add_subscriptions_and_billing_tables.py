"""Add subscriptions and billing tables

Revision ID: a1b2c3d4e5f6
Revises: 919c32e13aa2
Create Date: 2026-01-10

Phase 2 of Pricing Architecture: Subscription & Billing Models

Creates:
- subscriptions: One per organization, tracks plan tier and billing status
- usage_snapshots: Monthly usage records for billing and analytics
- billing_events: Audit log for all billing-related changes
- referrals: Referral program tracking

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "919c32e13aa2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create billing infrastructure for Phase 2 of pricing architecture."""

    # Step 1: Create subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Plan info
        sa.Column(
            "plan_tier",
            sa.String(20),
            nullable=False,
            server_default="observer",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "base_repo_limit",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
        # Billing period
        sa.Column("current_period_start", sa.DateTime, nullable=True),
        sa.Column("current_period_end", sa.DateTime, nullable=True),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("canceled_at", sa.DateTime, nullable=True),
        # Stripe references
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column(
            "stripe_metered_item_id",
            sa.String(255),
            nullable=True,
            comment="Stripe subscription item ID for overage billing",
        ),
        # Referral credits
        sa.Column(
            "referral_credit_cents",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
            comment="Accumulated referral credits in cents",
        ),
        # Admin override fields
        sa.Column(
            "is_manually_assigned",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="True if plan was assigned by admin, bypassing Stripe",
        ),
        sa.Column(
            "manually_assigned_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("manually_assigned_at", sa.DateTime, nullable=True),
        sa.Column(
            "manual_assignment_note",
            sa.String(500),
            nullable=True,
            comment="Reason for manual assignment, e.g., 'Founder account'",
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_subscriptions_organization_id", "subscriptions", ["organization_id"])
    op.create_index("ix_subscriptions_stripe_customer_id", "subscriptions", ["stripe_customer_id"])

    # Step 2: Create usage_snapshots table
    op.create_table(
        "usage_snapshots",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Period
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        # Counts
        sa.Column("repository_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("product_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "analysis_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
            comment="Number of AI analyses run this period",
        ),
        sa.Column(
            "member_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
            comment="Team size (for analytics, not billing)",
        ),
        # Computed at snapshot time
        sa.Column(
            "plan_tier",
            sa.String(20),
            nullable=False,
            comment="Plan tier at time of snapshot",
        ),
        sa.Column(
            "repo_limit",
            sa.Integer,
            nullable=False,
            comment="Base limit at time of snapshot",
        ),
        sa.Column(
            "overage_repos",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
            comment="Repos over base limit (billable on paid plans)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_usage_snapshots_organization_id", "usage_snapshots", ["organization_id"])
    op.create_index(
        "ix_usage_snapshots_period",
        "usage_snapshots",
        ["organization_id", "period_start"],
    )

    # Step 3: Create billing_events table
    op.create_table(
        "billing_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        # Change tracking
        sa.Column("previous_value", JSONB, nullable=True),
        sa.Column("new_value", JSONB, nullable=True),
        # Stripe reference
        sa.Column("stripe_event_id", sa.String(255), nullable=True),
        # Actor
        sa.Column(
            "actor_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_billing_events_organization_id", "billing_events", ["organization_id"])
    op.create_index("ix_billing_events_event_type", "billing_events", ["event_type"])
    op.create_index("ix_billing_events_stripe_event_id", "billing_events", ["stripe_event_id"])

    # Step 4: Create referrals table
    op.create_table(
        "referrals",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Referrer
        sa.Column(
            "referrer_org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "referrer_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Referee
        sa.Column(
            "referee_org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "referee_email",
            sa.String(255),
            nullable=True,
            comment="Email captured before signup",
        ),
        # Tracking
        sa.Column(
            "referral_code",
            sa.String(20),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "credit_amount",
            sa.Integer,
            nullable=False,
            server_default=sa.text("10000"),
            comment="Credit amount in cents (default $100)",
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("signed_up_at", sa.DateTime, nullable=True),
        sa.Column("converted_at", sa.DateTime, nullable=True),
        sa.Column("credited_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_referrals_referrer_org_id", "referrals", ["referrer_org_id"])
    op.create_index("ix_referrals_referral_code", "referrals", ["referral_code"])


def downgrade() -> None:
    """Remove billing infrastructure."""

    # Step 4: Drop referrals table
    op.drop_index("ix_referrals_referral_code", table_name="referrals")
    op.drop_index("ix_referrals_referrer_org_id", table_name="referrals")
    op.drop_table("referrals")

    # Step 3: Drop billing_events table
    op.drop_index("ix_billing_events_stripe_event_id", table_name="billing_events")
    op.drop_index("ix_billing_events_event_type", table_name="billing_events")
    op.drop_index("ix_billing_events_organization_id", table_name="billing_events")
    op.drop_table("billing_events")

    # Step 2: Drop usage_snapshots table
    op.drop_index("ix_usage_snapshots_period", table_name="usage_snapshots")
    op.drop_index("ix_usage_snapshots_organization_id", table_name="usage_snapshots")
    op.drop_table("usage_snapshots")

    # Step 1: Drop subscriptions table
    op.drop_index("ix_subscriptions_stripe_customer_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_organization_id", table_name="subscriptions")
    op.drop_table("subscriptions")
