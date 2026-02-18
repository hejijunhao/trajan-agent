"""Progress API: Contributors endpoint."""

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
from .types import ContributorDetail, DayOfWeekEntry, HeatmapRow
from .utils import generate_daily_activity, get_period_days

router = APIRouter()


@router.get("/products/{product_id}/contributors")
async def get_progress_contributors(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    sort_by: str = Query("commits", description="Sort by: commits, additions, last_active"),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get detailed contributor statistics for a product.

    Returns per-contributor breakdown including:
    - Stats: commits, LOC, files changed
    - Last active timestamp
    - Focus areas (top 3 directories)
    - Activity sparkline (daily commits)
    - Recent commits (last 3)
    """
    # Fetch commits using consolidated fetcher
    result = await fetch_product_commits(
        db=db,
        product_id=product_id,
        current_user=current_user,
        period=period,
        repo_ids=repo_ids,
        fetch_limit=200,
    )

    if not result:
        return {"contributors": [], "heatmap": {"rows": [], "dates": []}, "day_of_week_pattern": []}

    # Fetch commit stats for LOC calculation
    events = await fetch_commit_stats(db, result.github, result.repos, result.events)

    # Compute per-contributor details
    contributors = _compute_contributors(events, period, sort_by)

    # Compute heatmap and day-of-week pattern
    heatmap = _compute_heatmap(events, period)
    day_of_week = _compute_day_of_week(events)

    return {
        "contributors": contributors,
        "heatmap": heatmap,
        "day_of_week_pattern": [asdict(d) for d in day_of_week],
    }


def _compute_contributors(
    events: list[TimelineEvent], period: str, sort_by: str
) -> list[dict[str, Any]]:
    """Compute detailed per-contributor statistics."""
    # Sort events by timestamp (newest first) for last_active and recent_commits
    events.sort(key=lambda e: e.timestamp, reverse=True)

    # Group events by author
    author_events: dict[str, list[TimelineEvent]] = defaultdict(list)
    for event in events:
        author_events[event.commit_author].append(event)

    contributors: list[ContributorDetail] = []

    for author, author_commits in author_events.items():
        # Basic stats
        commits = len(author_commits)
        additions = sum(e.additions or 0 for e in author_commits)
        deletions = sum(e.deletions or 0 for e in author_commits)
        files_changed = sum(e.files_changed or 0 for e in author_commits)

        # Avatar (take from first commit)
        avatar_url = author_commits[0].commit_author_avatar if author_commits else None

        # Last active (already sorted newest first)
        last_active = author_commits[0].timestamp if author_commits else ""

        # Focus areas (top 3 repositories for this author)
        repo_counts: dict[str, int] = defaultdict(int)
        for event in author_commits:
            repo_counts[event.repository_name] += 1
        focus_areas = [
            repo for repo, _ in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        ]

        # Daily activity (sparkline)
        daily_counts: dict[str, int] = defaultdict(int)
        for event in author_commits:
            date = event.timestamp.split("T")[0]
            daily_counts[date] += 1
        daily_activity = generate_daily_activity(daily_counts, period)

        # Recent commits (last 3)
        recent_commits = [
            {
                "sha": e.commit_sha[:7],
                "message": e.commit_message,
                "repository": e.repository_name,
                "timestamp": e.timestamp,
                "url": e.commit_url,
            }
            for e in author_commits[:3]
        ]

        contributors.append(
            ContributorDetail(
                author=author,
                avatar_url=avatar_url,
                commits=commits,
                additions=additions,
                deletions=deletions,
                files_changed=files_changed,
                last_active=last_active,
                focus_areas=focus_areas,
                daily_activity=daily_activity,
                recent_commits=recent_commits,
            )
        )

    # Sort contributors
    if sort_by == "additions":
        contributors.sort(key=lambda c: c.additions, reverse=True)
    elif sort_by == "last_active":
        contributors.sort(key=lambda c: c.last_active, reverse=True)
    else:  # Default: commits
        contributors.sort(key=lambda c: c.commits, reverse=True)

    return [asdict(c) for c in contributors]


def _compute_heatmap(events: list[TimelineEvent], period: str) -> dict[str, Any]:
    """Compute activity heatmap: contributors × dates grid."""
    from datetime import UTC, datetime, timedelta

    period_days = get_period_days(period)
    today = datetime.now(UTC).date()
    dates = [
        (today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(period_days - 1, -1, -1)
    ]

    # Group events by author → date → count
    author_date_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    author_totals: dict[str, int] = defaultdict(int)
    author_avatars: dict[str, str | None] = {}

    for event in events:
        author = event.commit_author
        date = event.timestamp.split("T")[0]
        author_date_counts[author][date] += 1
        author_totals[author] += 1
        if author not in author_avatars:
            author_avatars[author] = event.commit_author_avatar

    # Sort by total commits descending (most active on top)
    sorted_authors = sorted(author_totals.keys(), key=lambda a: author_totals[a], reverse=True)

    rows = [
        asdict(
            HeatmapRow(
                author=author,
                avatar_url=author_avatars.get(author),
                cells=[{"date": d, "commits": author_date_counts[author].get(d, 0)} for d in dates],
            )
        )
        for author in sorted_authors
    ]

    return {"rows": rows, "dates": dates}


def _compute_day_of_week(events: list[TimelineEvent]) -> list[DayOfWeekEntry]:
    """Compute commit counts grouped by day of the week (Mon–Sun)."""
    from datetime import datetime

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    counts: dict[int, int] = defaultdict(int)

    for event in events:
        dt = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        counts[dt.weekday()] += 1  # 0=Mon, 6=Sun

    return [DayOfWeekEntry(day=day_names[i], commits=counts.get(i, 0)) for i in range(7)]
