"""Progress API: Velocity endpoint."""

import asyncio
import logging
import uuid as uuid_pkg
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ProductAccessContext,
    get_current_user,
    get_db_with_rls,
    get_product_access,
)
from app.domain import repository_ops
from app.models import User
from app.models.repository import Repository
from app.services.github import GitHubReadOperations
from app.services.github.exceptions import GitHubRepoRenamed
from app.services.github.timeline_types import TimelineEvent

from .commit_fetcher import fetch_commit_stats
from .types import RepoComparison, VelocityInsight
from .utils import (
    get_extended_period,
    get_period_days,
    get_period_start,
    handle_repo_rename,
    resolve_github_token,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/products/{product_id}/velocity")
async def get_velocity(
    product_id: uuid_pkg.UUID,
    period: str = Query("30d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get velocity data for charts and insights.

    Returns time-series data optimized for charts:
    - Daily velocity (commits, LOC, contributors per day)
    - Period comparison (vs previous period)
    - Pattern insights (busiest day, trends, etc.)

    Default period is 30d for velocity to show meaningful trends.
    """
    # Get GitHub-linked repositories
    repos = await repository_ops.get_github_repos_by_product(db, product_id=product_id)
    if not repos:
        return _empty_velocity_response()

    # Filter repositories if repo_ids provided
    if repo_ids:
        filter_ids = set(repo_ids.split(","))
        repos = [r for r in repos if str(r.id) in filter_ids]
        if not repos:
            return _empty_velocity_response()

    # Resolve GitHub token
    github_token = await resolve_github_token(db, current_user, product_id)
    if not github_token:
        return _empty_velocity_response()

    # Calculate period bounds (fetch extra for comparison)
    period_start = get_period_start(period)
    extended_period = get_extended_period(period)
    extended_start = get_period_start(extended_period)
    extended_since_str = extended_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fetch commits from all repos in parallel
    github = GitHubReadOperations(github_token)
    fetch_limit = 500  # Fetch more for velocity analysis

    async def fetch_repo_commits(
        repo: Repository,
    ) -> list[tuple[Repository, dict[str, Any]]]:
        if not repo.full_name:
            return []
        owner, name = repo.full_name.split("/")
        commits, _ = await github.get_commits_for_timeline(
            owner, name, repo.default_branch, per_page=fetch_limit
        )
        return [(repo, c) for c in commits]

    results = await asyncio.gather(
        *[fetch_repo_commits(r) for r in repos],
        return_exceptions=True,
    )

    # Handle renames and flatten results
    all_commits: list[tuple[Repository, dict[str, Any]]] = []
    repos_to_retry: list[Repository] = []

    for i, result in enumerate(results):
        if isinstance(result, GitHubRepoRenamed):
            repo = repos[i]
            updated_repo = await handle_repo_rename(db, github, repo, result)
            if updated_repo:
                repos_to_retry.append(updated_repo)
        elif isinstance(result, BaseException):
            logger.warning(f"Failed to fetch commits for repo: {result}")
            continue
        else:
            all_commits.extend(result)

    # Retry renamed repos
    if repos_to_retry:
        retry_results = await asyncio.gather(
            *[fetch_repo_commits(r) for r in repos_to_retry],
            return_exceptions=True,
        )
        for result in retry_results:
            if isinstance(result, BaseException):
                logger.warning(f"Retry failed for renamed repo: {result}")
                continue
            all_commits.extend(result)

    # Convert to TimelineEvent and filter by extended date range
    events: list[TimelineEvent] = []
    for repo, commit in all_commits:
        timestamp = commit["commit"]["committer"]["date"]

        if timestamp < extended_since_str:
            continue

        events.append(
            TimelineEvent(
                id=f"commit:{commit['sha']}",
                event_type="commit",
                timestamp=timestamp,
                repository_id=str(repo.id),
                repository_name=repo.name or "",
                repository_full_name=repo.full_name or "",
                commit_sha=commit["sha"],
                commit_message=commit["commit"]["message"].split("\n")[0][:100],
                commit_author=commit["commit"]["author"]["name"],
                commit_author_avatar=(
                    commit["author"]["avatar_url"] if commit.get("author") else None
                ),
                commit_url=commit["html_url"],
            )
        )

    if not events:
        return _empty_velocity_response()

    # Fetch commit stats for LOC calculation
    events = await fetch_commit_stats(db, github, repos, events)

    # Compute velocity data
    return _compute_velocity(events, period, period_start)


def _compute_velocity(
    events: list[TimelineEvent],
    period: str,
    period_start: datetime,
) -> dict[str, Any]:
    """Compute velocity data for charts and insights."""
    events.sort(key=lambda e: e.timestamp)

    # Split events into current period and previous period
    period_start_str = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    current_events = [e for e in events if e.timestamp >= period_start_str]
    previous_events = [e for e in events if e.timestamp < period_start_str]

    # Compute daily data for current period
    velocity_data = _compute_daily_velocity(current_events, period)

    # Compute totals for current and previous periods
    current_totals = _compute_period_totals(current_events)
    previous_totals = _compute_period_totals(previous_events)

    # Compute LOC data (daily additions/deletions)
    loc_data = [
        {"date": dp["date"], "additions": dp["additions"], "deletions": dp["deletions"]}
        for dp in velocity_data
    ]

    # Compute contributors over time
    contributors_data = [
        {"date": dp["date"], "contributors": dp["contributors"]} for dp in velocity_data
    ]

    # Compute insights
    insights = _compute_velocity_insights(velocity_data, current_totals, previous_totals, period)

    # Compute repo comparison
    repo_comparison = _compute_repo_comparison(current_events, period)

    return {
        "velocity_data": velocity_data,
        "loc_data": loc_data,
        "contributors_data": contributors_data,
        "current_totals": current_totals,
        "previous_totals": previous_totals,
        "insights": insights,
        "repo_comparison": [asdict(r) for r in repo_comparison],
    }


def _compute_daily_velocity(events: list[TimelineEvent], period: str) -> list[dict[str, Any]]:
    """Compute daily velocity data points."""
    days = get_period_days(period)

    today = datetime.now(UTC).date()
    daily_data: dict[str, dict[str, Any]] = {}

    for i in range(days - 1, -1, -1):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        daily_data[date_str] = {
            "date": date_str,
            "commits": 0,
            "additions": 0,
            "deletions": 0,
            "contributors": set(),
        }

    for event in events:
        date_str = event.timestamp.split("T")[0]
        if date_str in daily_data:
            daily_data[date_str]["commits"] += 1
            daily_data[date_str]["additions"] += event.additions or 0
            daily_data[date_str]["deletions"] += event.deletions or 0
            daily_data[date_str]["contributors"].add(event.commit_author)

    result = []
    for date_str in sorted(daily_data.keys()):
        data = daily_data[date_str]
        result.append(
            {
                "date": data["date"],
                "commits": data["commits"],
                "additions": data["additions"],
                "deletions": data["deletions"],
                "contributors": len(data["contributors"]),
            }
        )

    return result


def _compute_period_totals(events: list[TimelineEvent]) -> dict[str, Any]:
    """Compute totals for a set of events."""
    if not events:
        return {"commits": 0, "additions": 0, "deletions": 0, "contributors": 0, "files_changed": 0}

    contributors = set()
    total_additions = 0
    total_deletions = 0
    total_files = 0

    for event in events:
        contributors.add(event.commit_author)
        total_additions += event.additions or 0
        total_deletions += event.deletions or 0
        total_files += event.files_changed or 0

    return {
        "commits": len(events),
        "additions": total_additions,
        "deletions": total_deletions,
        "contributors": len(contributors),
        "files_changed": total_files,
    }


def _compute_velocity_insights(
    velocity_data: list[dict[str, Any]],
    current_totals: dict[str, Any],
    previous_totals: dict[str, Any],
    period: str,
) -> list[dict[str, Any]]:
    """Compute rule-based velocity insights."""
    insights: list[VelocityInsight] = []

    # 1. Velocity trend (compared to previous period)
    if previous_totals["commits"] > 0:
        change_pct = (
            (current_totals["commits"] - previous_totals["commits"])
            / previous_totals["commits"]
            * 100
        )
        if abs(change_pct) >= 5:
            direction = "up" if change_pct > 0 else "down"
            msg = f"Velocity is {direction} {abs(change_pct):.0f}% compared to previous {period}"
            insights.append(VelocityInsight(type="trend", message=msg, value=f"{change_pct:+.0f}%"))

    # 2. Peak day
    if velocity_data:
        peak_day = max(velocity_data, key=lambda d: d["commits"])
        if peak_day["commits"] > 0:
            peak_date = datetime.strptime(peak_day["date"], "%Y-%m-%d")
            formatted_date = peak_date.strftime("%b %d")
            insights.append(
                VelocityInsight(
                    type="peak",
                    message=f"Peak activity: {peak_day['commits']} commits on {formatted_date}",
                    value=str(peak_day["commits"]),
                )
            )

    # 3. Busiest day of week pattern
    if len(velocity_data) >= 7:
        day_totals: dict[str, int] = defaultdict(int)
        day_counts: dict[str, int] = defaultdict(int)
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        for data in velocity_data:
            date = datetime.strptime(data["date"], "%Y-%m-%d")
            day_name = day_names[date.weekday()]
            day_totals[day_name] += data["commits"]
            day_counts[day_name] += 1

        day_averages = {
            day: day_totals[day] / day_counts[day] for day in day_totals if day_counts[day] > 0
        }

        if day_averages:
            busiest_day = max(day_averages, key=lambda d: day_averages[d])
            avg_commits = day_averages[busiest_day]
            if avg_commits >= 1:
                insights.append(
                    VelocityInsight(
                        type="pattern",
                        message=f"Busiest day: {busiest_day} (avg {avg_commits:.1f} commits)",
                        value=busiest_day,
                    )
                )

    # 4. Net code growth
    net_loc = current_totals["additions"] - current_totals["deletions"]
    total_loc = current_totals["additions"] + current_totals["deletions"]
    if total_loc > 0:
        add_pct = current_totals["additions"] / total_loc * 100
        direction = "growth" if net_loc >= 0 else "reduction"
        insights.append(
            VelocityInsight(
                type="focus",
                message=f"Net code {direction}: {net_loc:+,} lines ({add_pct:.0f}% additions)",
                value=f"{net_loc:+,}",
            )
        )

    # 5. Average commits per day
    if velocity_data:
        active_days = len([d for d in velocity_data if d["commits"] > 0])
        total_commits = sum(d["commits"] for d in velocity_data)
        if active_days > 0:
            avg_per_active = total_commits / active_days
            avg_overall = total_commits / len(velocity_data)
            msg = f"Average: {avg_overall:.1f} commits/day ({avg_per_active:.1f} on active days)"
            insights.append(
                VelocityInsight(type="pattern", message=msg, value=f"{avg_overall:.1f}")
            )

    return [asdict(i) for i in insights]


def _compute_repo_comparison(events: list[TimelineEvent], period: str) -> list[RepoComparison]:
    """Compute per-repository comparison stats."""
    period_days = get_period_days(period)

    # Group events by repository
    repo_events: dict[str, list[TimelineEvent]] = defaultdict(list)
    repo_full_names: dict[str, str] = {}

    for event in events:
        repo_events[event.repository_name].append(event)
        if event.repository_name not in repo_full_names:
            repo_full_names[event.repository_name] = event.repository_full_name

    results: list[RepoComparison] = []
    for repo_name, repo_evts in repo_events.items():
        commits = len(repo_evts)
        additions = sum(e.additions or 0 for e in repo_evts)
        deletions = sum(e.deletions or 0 for e in repo_evts)
        unique_authors: set[str] = set()
        active_dates: set[str] = set()

        for e in repo_evts:
            unique_authors.add(e.commit_author)
            active_dates.add(e.timestamp.split("T")[0])

        active_days = len(active_dates)
        contributors = len(unique_authors)
        churn_ratio = round(deletions / additions, 2) if additions > 0 else 0.0

        active_ratio = active_days / period_days if period_days > 0 else 0
        if active_ratio >= 0.7:
            cadence = "daily"
        elif active_ratio >= 0.3:
            cadence = "sporadic"
        else:
            cadence = "inactive"

        results.append(
            RepoComparison(
                repository_name=repo_name,
                repository_full_name=repo_full_names.get(repo_name, repo_name),
                commits=commits,
                additions=additions,
                deletions=deletions,
                net_loc=additions - deletions,
                contributors=contributors,
                bus_factor=contributors,
                churn_ratio=churn_ratio,
                cadence=cadence,
                active_days=active_days,
            )
        )

    # Sort by commits descending
    results.sort(key=lambda r: r.commits, reverse=True)
    return results


def _empty_velocity_response() -> dict[str, Any]:
    """Return an empty velocity response."""
    empty_totals = {
        "commits": 0,
        "additions": 0,
        "deletions": 0,
        "contributors": 0,
        "files_changed": 0,
    }
    return {
        "velocity_data": [],
        "loc_data": [],
        "contributors_data": [],
        "current_totals": empty_totals.copy(),
        "previous_totals": empty_totals.copy(),
        "insights": [],
        "repo_comparison": [],
    }
