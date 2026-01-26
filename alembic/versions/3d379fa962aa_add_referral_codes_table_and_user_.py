"""add_referral_codes_table_and_user_invite_limit

Revision ID: 3d379fa962aa
Revises: a14b58c29632
Create Date: 2026-01-26 13:14:47.277535

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3d379fa962aa"
down_revision: Union[str, None] = "a14b58c29632"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add invite_limit column to users table
    op.add_column(
        "users",
        sa.Column(
            "invite_limit",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
            comment="Number of referral invites user can generate (adjustable by admin)",
        ),
    )

    # 2. Create referral_codes table
    op.create_table(
        "referral_codes",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "code",
            sa.String(length=12),
            nullable=False,
            comment="Unique referral code (e.g., SARAH-X7K9)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When code was used during sign-up",
        ),
        sa.Column(
            "redeemed_by_user_id",
            sa.UUID(),
            nullable=True,
            comment="User who redeemed this code",
        ),
        sa.Column(
            "converted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When recipient added payment (triggers sender reward)",
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    # 3. Create indexes for performance
    op.create_index(
        "ix_referral_codes_code",
        "referral_codes",
        ["code"],
        unique=True,
    )
    op.create_index(
        "ix_referral_codes_user_id",
        "referral_codes",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_referral_codes_user_id", table_name="referral_codes")
    op.drop_index("ix_referral_codes_code", table_name="referral_codes")

    # Drop referral_codes table
    op.drop_table("referral_codes")

    # Remove invite_limit column from users
    op.drop_column("users", "invite_limit")
