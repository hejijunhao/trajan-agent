"""Domain operations for team contributor AI summaries."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_contributor_summary import TeamContributorSummary


class TeamContributorSummaryOperations:
    """
    Operations for org-scoped team contributor summaries.

    Not user-scoped — shared cache per (org, period).
    Follows the same pattern as ProgressSummaryOperations.
    """

    def __init__(self) -> None:
        self.model = TeamContributorSummary

    async def get_by_org_period(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        period: str,
    ) -> TeamContributorSummary | None:
        """Fetch cached summary for an org + period."""
        stmt = select(TeamContributorSummary).where(
            and_(
                TeamContributorSummary.organization_id == organization_id,  # type: ignore[arg-type]
                TeamContributorSummary.period == period,  # type: ignore[arg-type]
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        period: str,
        summaries: dict[str, Any],
        team_summary: str,
        total_commits: int,
        total_contributors: int,
        last_activity_at: datetime | None = None,
    ) -> TeamContributorSummary:
        """Insert or update cached summary (atomic upsert)."""
        now = datetime.now(UTC)

        stmt = (
            insert(self.model)
            .values(
                organization_id=organization_id,
                period=period,
                summaries=summaries,
                team_summary=team_summary,
                total_commits=total_commits,
                total_contributors=total_contributors,
                last_activity_at=last_activity_at,
                generated_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["organization_id", "period"],
                set_={
                    "summaries": summaries,
                    "team_summary": team_summary,
                    "total_commits": total_commits,
                    "total_contributors": total_contributors,
                    "last_activity_at": last_activity_at,
                    "generated_at": now,
                    "updated_at": now,
                },
            )
            .returning(TeamContributorSummary)
        )

        result = await db.execute(stmt)
        await db.flush()
        return result.scalar_one()

    async def update_last_activity(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        period: str,
        last_activity_at: datetime,
    ) -> None:
        """Lightweight update when checked but no new commits."""
        stmt = select(self.model).where(
            and_(
                TeamContributorSummary.organization_id == organization_id,  # type: ignore[arg-type]
                TeamContributorSummary.period == period,  # type: ignore[arg-type]
            )
        )
        result = await db.execute(stmt)
        summary = result.scalar_one_or_none()
        if summary:
            summary.last_activity_at = last_activity_at
            summary.updated_at = datetime.now(UTC)
            db.add(summary)
            await db.flush()


team_contributor_summary_ops = TeamContributorSummaryOperations()
