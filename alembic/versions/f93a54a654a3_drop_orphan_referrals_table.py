"""drop_orphan_referrals_table

Revision ID: f93a54a654a3
Revises: 3d379fa962aa
Create Date: 2026-01-26 15:54:21.176846

This migration removes the orphan `referrals` table from a superseded design.
The referral system was redesigned from org-to-org (referrals) to user-to-user
(referral_codes) for better viral potential. The old table has 0 rows and is
safe to drop.

See: docs/executing/schema-drift-check.md
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f93a54a654a3"
down_revision: str | None = "3d379fa962aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop indexes first, then the table
    op.drop_index(op.f("ix_referrals_referral_code"), table_name="referrals")
    op.drop_index(op.f("ix_referrals_referrer_org_id"), table_name="referrals")
    op.drop_table("referrals")


def downgrade() -> None:
    # Recreate the orphan referrals table (org-to-org design, superseded)
    op.create_table(
        "referrals",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("referrer_org_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("referrer_user_id", sa.UUID(), autoincrement=False, nullable=True),
        sa.Column("referee_org_id", sa.UUID(), autoincrement=False, nullable=True),
        sa.Column(
            "referee_email",
            sa.VARCHAR(length=255),
            autoincrement=False,
            nullable=True,
            comment="Email captured before signup",
        ),
        sa.Column("referral_code", sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column(
            "status",
            sa.VARCHAR(length=20),
            server_default=sa.text("'pending'::character varying"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "credit_amount",
            sa.INTEGER(),
            server_default=sa.text("10000"),
            autoincrement=False,
            nullable=False,
            comment="Credit amount in cents (default $100)",
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "signed_up_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "converted_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "credited_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["referee_org_id"],
            ["organizations.id"],
            name=op.f("referrals_referee_org_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["referrer_org_id"],
            ["organizations.id"],
            name=op.f("referrals_referrer_org_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["referrer_user_id"],
            ["users.id"],
            name=op.f("referrals_referrer_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("referrals_pkey")),
        sa.UniqueConstraint(
            "referral_code",
            name=op.f("referrals_referral_code_key"),
        ),
    )
    op.create_index(
        op.f("ix_referrals_referrer_org_id"), "referrals", ["referrer_org_id"], unique=False
    )
    op.create_index(
        op.f("ix_referrals_referral_code"), "referrals", ["referral_code"], unique=False
    )
