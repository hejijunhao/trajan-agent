"""Domain operations for dashboard shipped summaries."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard_shipped_summary import DashboardShippedSummary


class DashboardShippedOperations:
    """
    Operations for AI-generated dashboard shipped summaries.

    Note: This doesn't extend BaseOperations because summaries
    are shared (not user-scoped) and use upsert patterns.
    """

    def __init__(self) -> None:
        self.model = DashboardShippedSummary

    async def get_by_product_period(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        period: str,
    ) -> DashboardShippedSummary | None:
        """
        Get existing shipped summary for a product and period.

        Args:
            db: Database session
            product_id: Product UUID
            period: Time period string (e.g., "7d", "30d")

        Returns:
            DashboardShippedSummary if exists, None otherwise
        """
        statement = select(DashboardShippedSummary).where(
            and_(
                DashboardShippedSummary.product_id == product_id,  # type: ignore[arg-type]
                DashboardShippedSummary.period == period,  # type: ignore[arg-type]
            )
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_products_period(
        self,
        db: AsyncSession,
        product_ids: list[uuid_pkg.UUID],
        period: str,
    ) -> list[DashboardShippedSummary]:
        """
        Get existing shipped summaries for multiple products and a period.

        Args:
            db: Database session
            product_ids: List of Product UUIDs
            period: Time period string (e.g., "7d", "30d")

        Returns:
            List of DashboardShippedSummary for products that have summaries
        """
        if not product_ids:
            return []

        statement = select(DashboardShippedSummary).where(
            and_(
                DashboardShippedSummary.product_id.in_(product_ids),  # type: ignore[attr-defined]
                DashboardShippedSummary.period == period,  # type: ignore[arg-type]
            )
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def upsert(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        period: str,
        items: list[dict[str, Any]],
        has_significant_changes: bool = True,
        total_commits: int = 0,
        total_additions: int = 0,
        total_deletions: int = 0,
        last_activity_at: datetime | None = None,
    ) -> DashboardShippedSummary:
        """
        Create or update a shipped summary.

        Uses PostgreSQL's INSERT ... ON CONFLICT DO UPDATE for atomicity.

        Args:
            db: Database session
            product_id: Product UUID
            period: Time period string
            items: List of shipped items [{description, category}]
            has_significant_changes: Whether meaningful changes occurred
            total_commits: Stats snapshot
            total_additions: Stats snapshot
            total_deletions: Stats snapshot
            last_activity_at: Timestamp of the newest commit seen

        Returns:
            The created or updated DashboardShippedSummary
        """
        now = datetime.now(UTC)

        stmt = (
            insert(self.model)
            .values(
                product_id=product_id,
                period=period,
                items=items,
                has_significant_changes=has_significant_changes,
                total_commits=total_commits,
                total_additions=total_additions,
                total_deletions=total_deletions,
                last_activity_at=last_activity_at,
                generated_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["product_id", "period"],
                set_={
                    "items": items,
                    "has_significant_changes": has_significant_changes,
                    "total_commits": total_commits,
                    "total_additions": total_additions,
                    "total_deletions": total_deletions,
                    "last_activity_at": last_activity_at,
                    "generated_at": now,
                    "updated_at": now,
                },
            )
            .returning(DashboardShippedSummary)
        )

        result = await db.execute(stmt)
        await db.flush()

        return result.scalar_one()

    async def update_last_activity(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        period: str,
        last_activity_at: datetime,
    ) -> None:
        """
        Update only the last_activity_at timestamp (skip-only update).

        Used when auto-progress checks for new commits but finds none.
        """
        stmt = select(self.model).where(
            and_(
                DashboardShippedSummary.product_id == product_id,  # type: ignore[arg-type]
                DashboardShippedSummary.period == period,  # type: ignore[arg-type]
            )
        )
        result = await db.execute(stmt)
        summary = result.scalar_one_or_none()
        if summary:
            summary.last_activity_at = last_activity_at
            summary.updated_at = datetime.now(UTC)
            db.add(summary)
            await db.flush()

    async def delete_by_product(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
    ) -> int:
        """
        Delete all shipped summaries for a product.

        Useful when a product is deleted or needs cache invalidation.

        Returns:
            Number of rows deleted
        """
        from sqlalchemy import delete

        stmt = delete(DashboardShippedSummary).where(
            DashboardShippedSummary.product_id == product_id  # type: ignore[arg-type]
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount  # type: ignore[attr-defined, no-any-return]


dashboard_shipped_ops = DashboardShippedOperations()
