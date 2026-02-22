"""Duplicate detection for work items.

Uses exact case-insensitive title match first, then falls back to
pg_trgm trigram similarity for fuzzy matching.
"""

import uuid as uuid_pkg

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_item import WorkItem

# Minimum trigram similarity score to consider a match (0.0–1.0).
# 0.6 catches paraphrased duplicates while avoiding false positives.
SIMILARITY_THRESHOLD = 0.6


async def find_duplicate_work_item(
    db: AsyncSession,
    product_id: uuid_pkg.UUID,
    title: str,
) -> WorkItem | None:
    """Find an existing open work item that duplicates the given title.

    Checks in order:
    1. Exact case-insensitive title match
    2. pg_trgm similarity >= SIMILARITY_THRESHOLD (highest similarity wins)

    Returns the matching WorkItem or None.
    """
    clean_title = title.strip()
    if not clean_title:
        return None

    # Base filter: same product, not done, not deleted
    base_filters = [
        WorkItem.product_id == product_id,
        WorkItem.status.notin_(["done", "completed", "deleted"]),  # type: ignore[union-attr]
        WorkItem.deleted_at.is_(None),  # type: ignore[union-attr]
    ]

    # 1. Exact case-insensitive match
    exact_stmt = (
        select(WorkItem)
        .where(*base_filters, func.lower(WorkItem.title) == clean_title.lower())
        .limit(1)
    )
    result = await db.execute(exact_stmt)
    exact_match = result.scalar_one_or_none()
    if exact_match is not None:
        return exact_match

    # 2. Fuzzy match via pg_trgm similarity (uses GIN index)
    similarity = func.similarity(WorkItem.title, clean_title)
    fuzzy_stmt = (
        select(WorkItem)
        .where(*base_filters, similarity >= SIMILARITY_THRESHOLD)
        .order_by(similarity.desc())
        .limit(1)
    )
    result = await db.execute(fuzzy_stmt)
    return result.scalar_one_or_none()
