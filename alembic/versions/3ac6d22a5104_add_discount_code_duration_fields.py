"""add_discount_code_duration_fields

Revision ID: 3ac6d22a5104
Revises: cde3c238696b
Create Date: 2026-03-02 14:00:20.417085

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3ac6d22a5104"
down_revision: str | None = "cde3c238696b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discount_codes",
        sa.Column("duration", sa.String(20), server_default="forever", nullable=False),
    )
    op.add_column("discount_codes", sa.Column("duration_in_months", sa.Integer(), nullable=True))

    # Ensure only valid duration values
    op.create_check_constraint(
        "ck_discount_codes_duration",
        "discount_codes",
        "duration IN ('forever', 'once', 'repeating')",
    )
    # duration_in_months must be set (>0) for repeating, NULL otherwise
    op.create_check_constraint(
        "ck_discount_codes_duration_months",
        "discount_codes",
        "(duration != 'repeating' OR (duration_in_months IS NOT NULL AND duration_in_months > 0))"
        " AND (duration = 'repeating' OR duration_in_months IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_discount_codes_duration_months", "discount_codes", type_="check")
    op.drop_constraint("ck_discount_codes_duration", "discount_codes", type_="check")
    op.drop_column("discount_codes", "duration_in_months")
    op.drop_column("discount_codes", "duration")
