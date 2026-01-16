"""Backfill orphan products with organization_id

Revision ID: a1cd5082aa4a
Revises: a1b2c3d4e5f7
Create Date: 2026-01-16 13:06:45.607280

This migration assigns orphan products (organization_id IS NULL) to their
creator's primary organization. The primary org is determined by:
1. First, any org where the user is an owner
2. Fallback to any org where the user is a member

Products without a valid org assignment are logged but left unchanged.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1cd5082aa4a'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Backfill organization_id for orphan products.

    For each product with organization_id IS NULL:
    1. Find the product's creator (user_id)
    2. Find that user's primary organization (prefer owner role)
    3. Set the product's organization_id
    """
    conn = op.get_bind()

    # Find all orphan products
    orphan_products = conn.execute(sa.text("""
        SELECT id, name, user_id
        FROM products
        WHERE organization_id IS NULL
    """)).fetchall()

    if not orphan_products:
        print("No orphan products found. Migration complete.")
        return

    print(f"Found {len(orphan_products)} orphan products to migrate.")

    migrated = 0
    skipped = 0

    for product in orphan_products:
        product_id = product.id
        product_name = product.name
        user_id = product.user_id

        # Find user's primary organization (prefer owner role, then any membership)
        primary_org = conn.execute(sa.text("""
            SELECT om.organization_id, om.role, o.name as org_name
            FROM organization_members om
            JOIN organizations o ON o.id = om.organization_id
            WHERE om.user_id = :user_id
            ORDER BY
                CASE om.role
                    WHEN 'owner' THEN 1
                    WHEN 'admin' THEN 2
                    ELSE 3
                END,
                om.joined_at ASC
            LIMIT 1
        """), {"user_id": user_id}).fetchone()

        if primary_org:
            org_id = primary_org.organization_id
            org_name = primary_org.org_name

            conn.execute(sa.text("""
                UPDATE products
                SET organization_id = :org_id, updated_at = NOW()
                WHERE id = :product_id
            """), {"org_id": org_id, "product_id": product_id})

            print(f"  Migrated: {product_name} -> {org_name}")
            migrated += 1
        else:
            print(f"  Skipped: {product_name} (user {user_id} has no organization)")
            skipped += 1

    print(f"\nMigration complete: {migrated} migrated, {skipped} skipped.")


def downgrade() -> None:
    """
    Downgrade is a no-op since we can't reliably determine which products
    were originally orphaned vs intentionally assigned to an org.

    If needed, orphan products can be identified by comparing updated_at
    timestamps around the time this migration ran.
    """
    print("Downgrade is a no-op for data backfill migrations.")
    pass
