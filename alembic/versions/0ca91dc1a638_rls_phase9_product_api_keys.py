"""Public Ticket API: work_items columns, product_api_keys table & RLS

Revision ID: 0ca91dc1a638
Revises: ee4cd3314269
Create Date: 2026-02-20

1. Adds source, reporter_email, reporter_name, ticket_metadata columns to work_items.
2. Creates product_api_keys table with indexes.
3. Enables Row-Level Security on product_api_keys.

Security Model:
- product_api_keys: Users with editor+ access to the product can SELECT.
  Users with editor+ access can INSERT (create keys).
  Users with editor+ access can UPDATE (revoke keys via revoked_at).
  No DELETE - keys are soft-deleted via revoked_at.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0ca91dc1a638"
down_revision: str | None = "ee4cd3314269"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ==========================================================================
    # 1. WORK_ITEMS — new columns for public ticket ingestion
    # ==========================================================================
    op.add_column(
        "work_items",
        sa.Column(
            "source",
            sqlmodel.sql.sqltypes.AutoString(length=30),
            nullable=True,
            server_default="web",
        ),
    )
    op.add_column(
        "work_items",
        sa.Column(
            "reporter_email",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "work_items",
        sa.Column(
            "reporter_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "work_items",
        sa.Column("ticket_metadata", sa.dialects.postgresql.JSONB(), nullable=True),
    )

    # ==========================================================================
    # 2. PRODUCT_API_KEYS — table creation
    # ==========================================================================
    op.create_table(
        "product_api_keys",
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
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "key_prefix", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False
        ),
        sa.Column(
            "name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "scopes",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_api_keys_id"), "product_api_keys", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_product_api_keys_product_id"),
        "product_api_keys",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_api_keys_key_hash",
        "product_api_keys",
        ["key_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_product_api_keys_created_by_user_id"),
        "product_api_keys",
        ["created_by_user_id"],
        unique=False,
    )

    # ==========================================================================
    # 3. PRODUCT_API_KEYS — Row-Level Security
    # ==========================================================================
    op.execute("ALTER TABLE product_api_keys ENABLE ROW LEVEL SECURITY")

    # Editors+ can view API keys for their products
    op.execute("""
        CREATE POLICY product_api_keys_editor_select ON product_api_keys
            FOR SELECT
            USING (can_edit_product(product_id))
    """)

    # Editors+ can create API keys
    op.execute("""
        CREATE POLICY product_api_keys_editor_insert ON product_api_keys
            FOR INSERT
            WITH CHECK (can_edit_product(product_id))
    """)

    # Editors+ can update API keys (revoke via revoked_at)
    op.execute("""
        CREATE POLICY product_api_keys_editor_update ON product_api_keys
            FOR UPDATE
            USING (can_edit_product(product_id))
            WITH CHECK (can_edit_product(product_id))
    """)


def downgrade() -> None:
    # RLS policies
    op.execute(
        "DROP POLICY IF EXISTS product_api_keys_editor_update ON product_api_keys"
    )
    op.execute(
        "DROP POLICY IF EXISTS product_api_keys_editor_insert ON product_api_keys"
    )
    op.execute(
        "DROP POLICY IF EXISTS product_api_keys_editor_select ON product_api_keys"
    )
    op.execute("ALTER TABLE product_api_keys DISABLE ROW LEVEL SECURITY")

    # Indexes & table
    op.drop_index(
        op.f("ix_product_api_keys_created_by_user_id"), table_name="product_api_keys"
    )
    op.drop_index("ix_product_api_keys_key_hash", table_name="product_api_keys")
    op.drop_index(
        op.f("ix_product_api_keys_product_id"), table_name="product_api_keys"
    )
    op.drop_index(op.f("ix_product_api_keys_id"), table_name="product_api_keys")
    op.drop_table("product_api_keys")

    # work_items columns
    op.drop_column("work_items", "ticket_metadata")
    op.drop_column("work_items", "reporter_name")
    op.drop_column("work_items", "reporter_email")
    op.drop_column("work_items", "source")
