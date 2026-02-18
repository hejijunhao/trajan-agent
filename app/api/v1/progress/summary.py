"""Progress API: Summary endpoint."""

import re
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
from .types import CommitQuality, CommitTypeBreakdown, ContributorStats, FocusArea, PulseData
from .utils import generate_daily_activity, get_extended_period, get_period_days

router = APIRouter()


@router.get("/products/{product_id}/summary")
async def get_progress_summary(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get progress summary for a product.

    Returns aggregated statistics including:
    - Total commits, contributors, additions, deletions
    - Focus areas (top directories by commit count)
    - Top contributors with their stats
    - Daily activity breakdown (for sparkline)
    - Recent commits preview
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
        return _empty_summary_response(period)

    # Fetch commit stats for LOC calculation
    events = await fetch_commit_stats(db, result.github, result.repos, result.events)

    # Fetch previous period commits for velocity trend
    extended_period = get_extended_period(period)
    prev_result = await fetch_product_commits(
        db=db,
        product_id=product_id,
        current_user=current_user,
        period=extended_period,
        repo_ids=repo_ids,
        fetch_limit=200,
    )

    prev_events: list[TimelineEvent] = []
    if prev_result:
        prev_events = prev_result.events

    # Compute aggregations
    return _compute_summary(events, prev_events, period)


def _compute_summary(
    events: list[TimelineEvent],
    prev_events: list[TimelineEvent],
    period: str,
) -> dict[str, Any]:
    """Compute summary statistics from events."""
    # Sort events by timestamp (newest first)
    events.sort(key=lambda e: e.timestamp, reverse=True)

    # Aggregate stats
    total_commits = len(events)
    total_additions = sum(e.additions or 0 for e in events)
    total_deletions = sum(e.deletions or 0 for e in events)

    # Unique contributors
    contributors: dict[str, ContributorStats] = {}
    for event in events:
        author = event.commit_author
        if author not in contributors:
            contributors[author] = ContributorStats(
                author=author,
                avatar_url=event.commit_author_avatar,
                commits=0,
                additions=0,
                deletions=0,
                files_changed=0,
            )
        stats = contributors[author]
        stats.commits += 1
        stats.additions += event.additions or 0
        stats.deletions += event.deletions or 0
        stats.files_changed += event.files_changed or 0

    total_contributors = len(contributors)

    # Top contributors (sorted by commits, top 5)
    top_contributors = sorted(contributors.values(), key=lambda c: c.commits, reverse=True)[:5]

    # Focus areas (aggregate by repository name as proxy)
    focus_area_counts: dict[str, int] = defaultdict(int)
    for event in events:
        focus_area_counts[event.repository_name] += 1

    focus_areas = [
        FocusArea(path=path, commits=count)
        for path, count in sorted(focus_area_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    # Daily activity breakdown
    daily_counts: dict[str, int] = defaultdict(int)
    for event in events:
        date = event.timestamp.split("T")[0]
        daily_counts[date] += 1

    # Generate all days in period for sparkline (even if 0 commits)
    daily_activity = generate_daily_activity(daily_counts, period)

    # Recent commits (top 5)
    recent_commits = [
        {
            "id": e.id,
            "sha": e.commit_sha[:7],
            "message": e.commit_message,
            "author": e.commit_author,
            "author_avatar": e.commit_author_avatar,
            "repository": e.repository_name,
            "timestamp": e.timestamp,
            "url": e.commit_url,
            "additions": e.additions,
            "deletions": e.deletions,
        }
        for e in events[:5]
    ]

    # Compute pulse data
    pulse = _compute_pulse(events, prev_events, daily_activity, period)

    # Compute commit quality
    commit_quality = _compute_commit_quality(events)

    return {
        "total_commits": total_commits,
        "total_contributors": total_contributors,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "focus_areas": [asdict(fa) for fa in focus_areas],
        "top_contributors": [asdict(tc) for tc in top_contributors],
        "daily_activity": daily_activity,
        "recent_commits": recent_commits,
        "pulse": asdict(pulse),
        "commit_quality": asdict(commit_quality),
    }


def _compute_pulse(
    current_events: list[TimelineEvent],
    prev_events: list[TimelineEvent],
    daily_activity: list[dict[str, Any]],
    period: str,
) -> PulseData:
    """Compute development pulse metrics."""
    period_days = get_period_days(period)
    current_count = len(current_events)

    # Previous period: filter prev_events to only those NOT in the current period
    # prev_events covers the extended period, so subtract current events
    current_ids = {e.id for e in current_events}
    prev_only = [e for e in prev_events if e.id not in current_ids]
    prev_count = len(prev_only)

    # Velocity trend
    if prev_count == 0:
        velocity_trend = 0.0 if current_count == 0 else 100.0
    else:
        velocity_trend = round(((current_count - prev_count) / prev_count) * 100, 1)

    if velocity_trend > 10:
        velocity_label = "faster"
    elif velocity_trend < -10:
        velocity_label = "slower"
    else:
        velocity_label = "steady"

    # Team streak: consecutive days with ≥1 commit, walking backward from end of period
    team_streak_days = 0
    for day in reversed(daily_activity):
        if day["commits"] > 0:
            team_streak_days += 1
        else:
            break

    # Active days in period
    active_days_in_period = sum(1 for day in daily_activity if day["commits"] > 0)

    return PulseData(
        velocity_trend=velocity_trend,
        velocity_label=velocity_label,
        team_streak_days=team_streak_days,
        active_days_in_period=active_days_in_period,
        period_days=period_days,
    )


# Conventional commit type patterns (case-insensitive)
_COMMIT_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Features", re.compile(r"^feat(\(.*?\))?[!:]", re.IGNORECASE)),
    ("Fixes", re.compile(r"^fix(\(.*?\))?[!:]", re.IGNORECASE)),
    ("Refactors", re.compile(r"^refactor(\(.*?\))?[!:]", re.IGNORECASE)),
    ("Docs", re.compile(r"^docs(\(.*?\))?[!:]", re.IGNORECASE)),
    ("Tests", re.compile(r"^test(\(.*?\))?[!:]", re.IGNORECASE)),
    ("Chores", re.compile(r"^(chore|ci|build|style|perf)(\(.*?\))?[!:]", re.IGNORECASE)),
]


def _classify_commit(message: str) -> tuple[str, bool]:
    """Classify a commit message. Returns (type, is_conventional)."""
    for type_name, pattern in _COMMIT_TYPE_PATTERNS:
        if pattern.match(message):
            return type_name, True
    return "Other", False


def _compute_commit_quality(events: list[TimelineEvent]) -> CommitQuality:
    """Compute commit quality heuristics from commit metadata."""
    if not events:
        return CommitQuality(
            commit_types=[],
            avg_commit_size_loc=0,
            avg_files_per_commit=0.0,
            large_commits=0,
            conventional_commit_pct=0.0,
            total_analyzed=0,
        )

    total = len(events)
    type_counts: dict[str, int] = defaultdict(int)
    conventional_count = 0
    total_loc = 0
    total_files = 0
    large_count = 0

    for e in events:
        commit_type, is_conventional = _classify_commit(e.commit_message)
        type_counts[commit_type] += 1
        if is_conventional:
            conventional_count += 1

        loc = (e.additions or 0) + (e.deletions or 0)
        total_loc += loc
        total_files += e.files_changed or 0
        if loc > 500:
            large_count += 1

    # Build sorted type breakdown
    commit_types = [
        asdict(
            CommitTypeBreakdown(
                type=t,
                count=c,
                percentage=round((c / total) * 100, 1),
            )
        )
        for t, c in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    return CommitQuality(
        commit_types=commit_types,
        avg_commit_size_loc=round(total_loc / total),
        avg_files_per_commit=round(total_files / total, 1),
        large_commits=large_count,
        conventional_commit_pct=round((conventional_count / total) * 100, 1),
        total_analyzed=total,
    )


def _empty_summary_response(period: str = "7d") -> dict[str, Any]:
    """Return an empty summary response."""
    return {
        "total_commits": 0,
        "total_contributors": 0,
        "total_additions": 0,
        "total_deletions": 0,
        "focus_areas": [],
        "top_contributors": [],
        "daily_activity": [],
        "recent_commits": [],
        "pulse": asdict(
            PulseData(
                velocity_trend=0.0,
                velocity_label="steady",
                team_streak_days=0,
                active_days_in_period=0,
                period_days=get_period_days(period),
            )
        ),
        "commit_quality": asdict(
            CommitQuality(
                commit_types=[],
                avg_commit_size_loc=0,
                avg_files_per_commit=0.0,
                large_commits=0,
                conventional_commit_pct=0.0,
                total_analyzed=0,
            )
        ),
    }
