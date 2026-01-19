"""Domain operations for commit stats cache."""

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commit_stats_cache import CommitStatsCache


class CommitStatsCacheOperations:
    """
    Operations for commit stats cache.

    Note: This doesn't extend BaseOperations because the cache
    is shared (not user-scoped) and has different access patterns.
    """

    def __init__(self) -> None:
        self.model = CommitStatsCache

    async def get_bulk_by_repo_shas(
        self,
        db: AsyncSession,
        lookups: list[tuple[str, str]],
    ) -> dict[tuple[str, str], CommitStatsCache]:
        """
        Bulk fetch cached stats for multiple commits.

        Args:
            db: Database session
            lookups: List of (repository_full_name, commit_sha) tuples

        Returns:
            Dict mapping (full_name, sha) -> cached stats.
            Missing entries are simply not in the returned dict.
        """
        if not lookups:
            return {}

        conditions = [
            and_(
                CommitStatsCache.repository_full_name == full_name,  # type: ignore[arg-type]
                CommitStatsCache.commit_sha == sha,  # type: ignore[arg-type]
            )
            for full_name, sha in lookups
        ]

        statement = select(CommitStatsCache).where(or_(*conditions))
        result = await db.execute(statement)
        rows = result.scalars().all()

        return {(row.repository_full_name, row.commit_sha): row for row in rows}

    async def bulk_upsert(
        self,
        db: AsyncSession,
        stats_list: list[dict[str, str | int]],
    ) -> int:
        """
        Bulk insert commit stats, ignoring duplicates.

        Args:
            db: Database session
            stats_list: List of dicts with keys:
                - full_name: str
                - sha: str
                - additions: int
                - deletions: int
                - files_changed: int

        Returns:
            Count of newly inserted rows.
        """
        if not stats_list:
            return 0

        stmt = (
            insert(self.model)
            .values(
                [
                    {
                        "repository_full_name": s["full_name"],
                        "commit_sha": s["sha"],
                        "additions": s["additions"],
                        "deletions": s["deletions"],
                        "files_changed": s["files_changed"],
                    }
                    for s in stats_list
                ]
            )
            .on_conflict_do_nothing(index_elements=["repository_full_name", "commit_sha"])
        )

        await db.execute(stmt)
        await db.flush()

        return len(stats_list)


commit_stats_cache_ops = CommitStatsCacheOperations()
