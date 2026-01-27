"""Add announcement table

Revision ID: 4cd213aad746
Revises: f93a54a654a3
Create Date: 2026-01-27 08:40:30.649616

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4cd213aad746"
down_revision: str | None = "f93a54a654a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create announcement table for system-wide banners
    op.create_table(
        "announcement",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Content
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("link_url", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column("link_text", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        # Styling
        sa.Column(
            "variant",
            sa.String(length=20),
            server_default=sa.text("'info'"),
            nullable=False,
        ),
        # Visibility
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        # Behavior
        sa.Column("is_dismissible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("dismiss_key", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        # Targeting (future-proofing)
        sa.Column(
            "target_audience",
            sa.String(length=20),
            server_default=sa.text("'all'"),
            nullable=False,
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Index for primary key lookups
    op.create_index(op.f("ix_announcement_id"), "announcement", ["id"], unique=False)

    # Composite index for efficient active announcement queries
    op.create_index(
        "idx_announcement_active",
        "announcement",
        ["is_active", "starts_at", "ends_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_announcement_active", table_name="announcement")
    op.drop_index(op.f("ix_announcement_id"), table_name="announcement")
    op.drop_table("announcement")
