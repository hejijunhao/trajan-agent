"""Domain operations for progress summary AI narratives."""

import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.progress_summary import ProgressSummary


class ProgressSummaryOperations:
    """
    Operations for AI-generated progress summaries.

    Note: This doesn't extend BaseOperations because summaries
    are shared (not user-scoped) and use upsert patterns.
    """

    def __init__(self) -> None:
        self.model = ProgressSummary

    async def get_by_product_period(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        period: str,
    ) -> ProgressSummary | None:
        """
        Get existing summary for a product and period.

        Args:
            db: Database session
            product_id: Product UUID
            period: Time period string (e.g., "7d", "30d")

        Returns:
            ProgressSummary if exists, None otherwise
        """
        statement = select(ProgressSummary).where(
            and_(
                ProgressSummary.product_id == product_id,  # type: ignore[arg-type]
                ProgressSummary.period == period,  # type: ignore[arg-type]
            )
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        period: str,
        summary_text: str,
        total_commits: int = 0,
        total_contributors: int = 0,
        total_additions: int = 0,
        total_deletions: int = 0,
    ) -> ProgressSummary:
        """
        Create or update a progress summary.

        Uses PostgreSQL's INSERT ... ON CONFLICT DO UPDATE for atomicity.

        Args:
            db: Database session
            product_id: Product UUID
            period: Time period string
            summary_text: AI-generated narrative
            total_commits: Stats snapshot
            total_contributors: Stats snapshot
            total_additions: Stats snapshot
            total_deletions: Stats snapshot

        Returns:
            The created or updated ProgressSummary
        """
        now = datetime.now(UTC)

        stmt = (
            insert(self.model)
            .values(
                product_id=product_id,
                period=period,
                summary_text=summary_text,
                total_commits=total_commits,
                total_contributors=total_contributors,
                total_additions=total_additions,
                total_deletions=total_deletions,
                generated_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["product_id", "period"],
                set_={
                    "summary_text": summary_text,
                    "total_commits": total_commits,
                    "total_contributors": total_contributors,
                    "total_additions": total_additions,
                    "total_deletions": total_deletions,
                    "generated_at": now,
                    "updated_at": now,
                },
            )
            .returning(ProgressSummary)
        )

        result = await db.execute(stmt)
        await db.flush()

        return result.scalar_one()


progress_summary_ops = ProgressSummaryOperations()
