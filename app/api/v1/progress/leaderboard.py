"""Progress API: Leaderboard endpoint."""

import uuid as uuid_pkg
from collections import defaultdict
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ProductAccessContext,
    get_current_user,
    get_db_with_rls,
    get_product_access,
)
from app.models import User
from app.services.github.timeline_types import TimelineEvent

from .commit_fetcher import fetch_commit_stats, fetch_product_commits
from .types import LeaderboardEntry
from .utils import generate_daily_activity, get_period_days

router = APIRouter()

VALID_RANK_BY = {"commits", "additions", "active_days", "files_changed"}


@router.get("/products/{product_id}/leaderboard")
async def get_progress_leaderboard(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    rank_by: str = Query(
        "commits", description="Rank by: commits, additions, active_days, files_changed"
    ),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get contributor leaderboard for a product.

    Returns ranked contributors with detailed metrics, sorted by the selected criterion.
    """
    if rank_by not in VALID_RANK_BY:
        rank_by = "commits"

    result = await fetch_product_commits(
        db=db,
        product_id=product_id,
        current_user=current_user,
        period=period,
        repo_ids=repo_ids,
        fetch_limit=200,
    )

    if not result:
        return {"entries": [], "total_contributors": 0, "period": period, "ranked_by": rank_by}

    events = await fetch_commit_stats(db, result.github, result.repos, result.events)

    entries = _compute_leaderboard(events, period, rank_by)

    return {
        "entries": entries,
        "total_contributors": len(entries),
        "period": period,
        "ranked_by": rank_by,
    }


def _compute_leaderboard(
    events: list[TimelineEvent], period: str, rank_by: str
) -> list[dict[str, Any]]:
    """Compute leaderboard entries from events."""
    events.sort(key=lambda e: e.timestamp, reverse=True)

    author_events: dict[str, list[TimelineEvent]] = defaultdict(list)
    for event in events:
        author_events[event.commit_author].append(event)

    entries: list[LeaderboardEntry] = []
    period_days = get_period_days(period)

    for author, author_commits in author_events.items():
        commits = len(author_commits)
        additions = sum(e.additions or 0 for e in author_commits)
        deletions = sum(e.deletions or 0 for e in author_commits)
        files_changed = sum(e.files_changed or 0 for e in author_commits)
        avatar_url = author_commits[0].commit_author_avatar if author_commits else None

        repos_contributed_to = len({e.repository_name for e in author_commits})
        active_day_set = {e.timestamp.split("T")[0] for e in author_commits}
        active_days = len(active_day_set)
        avg_commits_per_active_day = round(commits / active_days, 1) if active_days > 0 else 0.0

        daily_counts: dict[str, int] = defaultdict(int)
        for event in author_commits:
            date = event.timestamp.split("T")[0]
            daily_counts[date] += 1
        daily_activity = generate_daily_activity(daily_counts, period)

        entries.append(
            LeaderboardEntry(
                rank=0,  # assigned after sorting
                author=author,
                avatar_url=avatar_url,
                commits=commits,
                additions=additions,
                deletions=deletions,
                net_loc=additions - deletions,
                files_changed=files_changed,
                repos_contributed_to=repos_contributed_to,
                active_days=active_days,
                avg_commits_per_active_day=avg_commits_per_active_day,
                daily_activity=daily_activity,
                period_days=period_days,
            )
        )

    # Sort by rank_by criterion
    sort_key = {
        "commits": lambda e: e.commits,
        "additions": lambda e: e.additions,
        "active_days": lambda e: e.active_days,
        "files_changed": lambda e: e.files_changed,
    }.get(rank_by, lambda e: e.commits)

    entries.sort(key=sort_key, reverse=True)

    # Assign ranks
    for i, entry in enumerate(entries):
        entry.rank = i + 1

    return [asdict(e) for e in entries]
