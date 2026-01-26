"""add_cascade_to_products_organization_fk

Revision ID: a14b58c29632
Revises: 3520679817a5
Create Date: 2026-01-26 12:30:08.215388

Adds ON DELETE CASCADE to products.organization_id foreign key.
This ensures that when an organization is deleted, all its products
are automatically deleted (which then cascades to repos, work items, docs, etc.)

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a14b58c29632"
down_revision: str | None = "3520679817a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop existing FK constraint (without CASCADE)
    op.drop_constraint("products_organization_id_fkey", "products", type_="foreignkey")

    # Recreate FK constraint WITH CASCADE
    op.create_foreign_key(
        "products_organization_id_fkey",
        "products",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Drop CASCADE FK constraint
    op.drop_constraint("products_organization_id_fkey", "products", type_="foreignkey")

    # Recreate FK constraint WITHOUT CASCADE (original behavior)
    op.create_foreign_key(
        "products_organization_id_fkey",
        "products",
        "organizations",
        ["organization_id"],
        ["id"],
    )
