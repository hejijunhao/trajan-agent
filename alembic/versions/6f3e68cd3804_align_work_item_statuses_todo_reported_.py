"""Align work item statuses: todo→reported, done→completed

Revision ID: 6f3e68cd3804
Revises: af976c33d979
Create Date: 2026-02-26 11:55:39.380413

Converges the Tasks tab and Feedback Tickets tab onto one status lifecycle.
Legacy 'todo' statuses become 'reported'; legacy 'done' becomes 'completed'.
This is a data-only migration — no schema changes.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "6f3e68cd3804"
down_revision: str | None = "af976c33d979"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE work_items SET status = 'reported' WHERE status = 'todo'")
    op.execute("UPDATE work_items SET status = 'completed' WHERE status = 'done'")


def downgrade() -> None:
    op.execute("UPDATE work_items SET status = 'todo' WHERE status = 'reported'")
    op.execute("UPDATE work_items SET status = 'done' WHERE status = 'completed'")
