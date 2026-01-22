"""Progress API endpoints (serves Progress tab Summary view)."""

import asyncio
import uuid as uuid_pkg
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.domain import commit_stats_cache_ops, product_ops, repository_ops
from app.domain.preferences_operations import preferences_ops
from app.models import User
from app.models.repository import Repository
from app.services.github import GitHubReadOperations
from app.services.github.timeline_types import TimelineEvent

router = APIRouter(prefix="/progress", tags=["progress"])

# Concurrency limit for fetching commit stats
MAX_CONCURRENT_STAT_FETCHES = 10


@dataclass
class ContributorStats:
    """Statistics for a single contributor."""

    author: str
    avatar_url: str | None
    commits: int
    additions: int
    deletions: int
    files_changed: int


@dataclass
class FocusArea:
    """A directory/path with commit activity."""

    path: str
    commits: int


@dataclass
class DailyActivity:
    """Activity for a single day."""

    date: str  # YYYY-MM-DD
    commits: int


@dataclass
class ProgressSummaryResponse:
    """Response structure for progress summary endpoint."""

    # Aggregate stats
    total_commits: int
    total_contributors: int
    total_additions: int
    total_deletions: int

    # Breakdown data
    focus_areas: list[dict[str, Any]]
    top_contributors: list[dict[str, Any]]
    daily_activity: list[dict[str, Any]]
    recent_commits: list[dict[str, Any]]


def extract_focus_area(file_path: str) -> str:
    """Extract the top-level directory from a file path.

    Examples:
        "backend/app/api/v1/timeline.py" -> "backend"
        "frontend/src/components/Button.tsx" -> "frontend"
        "README.md" -> "."
    """
    parts = file_path.split("/")
    if len(parts) > 1:
        return parts[0]
    return "."  # Root-level files


def get_period_start(period: str) -> datetime:
    """Convert period string to start datetime.

    Args:
        period: One of "24h", "48h", "7d", "14d", "30d", "90d", "365d"

    Returns:
        UTC datetime for the start of the period
    """
    now = datetime.now(timezone.utc)

    period_map = {
        "24h": timedelta(hours=24),
        "48h": timedelta(hours=48),
        "7d": timedelta(days=7),
        "14d": timedelta(days=14),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "365d": timedelta(days=365),
    }

    delta = period_map.get(period, timedelta(days=7))  # Default to 7d
    return now - delta


@router.get("/products/{product_id}/summary")
async def get_progress_summary(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
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

    # 1. Verify product access
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # 2. Get GitHub-linked repositories
    repos = await repository_ops.get_github_repos_by_product(db, product_id=product_id)
    if not repos:
        return _empty_summary_response()

    # 2b. Filter repositories if repo_ids provided
    if repo_ids:
        filter_ids = set(repo_ids.split(","))
        repos = [r for r in repos if str(r.id) in filter_ids]
        if not repos:
            return _empty_summary_response()

    # 3. Get GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    github_token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token required")

    # 4. Calculate period bounds
    period_start = get_period_start(period)
    since_str = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 5. Fetch commits from all repos in parallel
    # Fetch more commits than typical to get good coverage for stats
    github = GitHubReadOperations(github_token)
    fetch_limit = 200  # Fetch up to 200 commits per repo for aggregation

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

    # 6. Flatten and filter errors
    all_commits: list[tuple[Repository, dict[str, Any]]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        all_commits.extend(result)

    # 7. Convert to TimelineEvent and filter by date
    events: list[TimelineEvent] = []
    for repo, commit in all_commits:
        timestamp = commit["commit"]["committer"]["date"]

        # Filter by period
        if timestamp < since_str:
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
        return _empty_summary_response()

    # 8. Fetch commit stats for LOC calculation
    events = await _fetch_commit_stats(db, github, repos, events)

    # 9. Compute aggregations
    return _compute_summary(events, period)


async def _fetch_commit_stats(
    db: AsyncSession,
    github: GitHubReadOperations,
    repos: list[Repository],
    events: list[TimelineEvent],
) -> list[TimelineEvent]:
    """Fetch commit stats (additions, deletions, files) with caching."""

    # Build repo map
    repo_map: dict[str, tuple[str, str]] = {}
    for repo in repos:
        if repo.full_name:
            owner_name, repo_name = repo.full_name.split("/")
            repo_map[repo.full_name] = (owner_name, repo_name)

    # Bulk fetch from cache
    lookup_keys = [(e.repository_full_name, e.commit_sha) for e in events]
    cached_stats = await commit_stats_cache_ops.get_bulk_by_repo_shas(db, lookup_keys)

    # Identify cache misses and populate hits
    events_needing_fetch: list[TimelineEvent] = []
    for event in events:
        key = (event.repository_full_name, event.commit_sha)
        if key in cached_stats:
            cached = cached_stats[key]
            event.additions = cached.additions
            event.deletions = cached.deletions
            event.files_changed = cached.files_changed
        else:
            events_needing_fetch.append(event)

    # Fetch missing stats from GitHub (with concurrency limit)
    if events_needing_fetch:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_STAT_FETCHES)
        stats_to_cache: list[dict[str, str | int]] = []

        async def fetch_and_cache_stats(event: TimelineEvent) -> None:
            repo_info = repo_map.get(event.repository_full_name)
            if not repo_info:
                return
            owner_name, repo_name = repo_info

            async with semaphore:
                stats = await github.get_commit_detail(owner_name, repo_name, event.commit_sha)
                if stats:
                    event.additions = stats["additions"]
                    event.deletions = stats["deletions"]
                    event.files_changed = stats["files_changed"]
                    stats_to_cache.append({
                        "full_name": event.repository_full_name,
                        "sha": event.commit_sha,
                        "additions": stats["additions"],
                        "deletions": stats["deletions"],
                        "files_changed": stats["files_changed"],
                    })

        await asyncio.gather(
            *[fetch_and_cache_stats(e) for e in events_needing_fetch],
            return_exceptions=True,
        )

        # Bulk insert newly fetched stats into cache
        if stats_to_cache:
            await commit_stats_cache_ops.bulk_upsert(db, stats_to_cache)

    return events


def _compute_summary(events: list[TimelineEvent], period: str) -> dict[str, Any]:
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

    # Focus areas (aggregate by top-level directory)
    # Note: We don't have file paths in the basic commit data, so we use repository as proxy
    # In Phase 7, we'll enhance this with actual file path data
    focus_area_counts: dict[str, int] = defaultdict(int)
    for event in events:
        # Use repository name as focus area for now
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
    daily_activity = _generate_daily_activity(daily_counts, period)

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

    return {
        "total_commits": total_commits,
        "total_contributors": total_contributors,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "focus_areas": [asdict(fa) for fa in focus_areas],
        "top_contributors": [asdict(tc) for tc in top_contributors],
        "daily_activity": daily_activity,
        "recent_commits": recent_commits,
    }


def _generate_daily_activity(
    daily_counts: dict[str, int], period: str
) -> list[dict[str, Any]]:
    """Generate daily activity list with all days in period."""

    period_days = {
        "24h": 1,
        "48h": 2,
        "7d": 7,
        "14d": 14,
        "30d": 30,
        "90d": 90,
        "365d": 365,
    }

    days = period_days.get(period, 7)
    today = datetime.now(timezone.utc).date()

    activity = []
    for i in range(days - 1, -1, -1):  # Oldest to newest
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        activity.append({
            "date": date_str,
            "commits": daily_counts.get(date_str, 0),
        })

    return activity


def _empty_summary_response() -> dict[str, Any]:
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
    }


# =============================================================================
# Contributors Endpoint (Phase 4)
# =============================================================================


@dataclass
class ContributorDetail:
    """Detailed statistics for a single contributor in the Contributors tab."""

    author: str
    avatar_url: str | None
    commits: int
    additions: int
    deletions: int
    files_changed: int
    last_active: str  # ISO timestamp
    focus_areas: list[str]  # Top 3 directories
    daily_activity: list[dict[str, Any]]  # Sparkline data
    recent_commits: list[dict[str, Any]]  # Last 3 commits


@router.get("/products/{product_id}/contributors")
async def get_progress_contributors(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    sort_by: str = Query("commits", description="Sort by: commits, additions, last_active"),
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

    # 1. Verify product access
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # 2. Get GitHub-linked repositories
    repos = await repository_ops.get_github_repos_by_product(db, product_id=product_id)
    if not repos:
        return {"contributors": []}

    # 2b. Filter repositories if repo_ids provided
    if repo_ids:
        filter_ids = set(repo_ids.split(","))
        repos = [r for r in repos if str(r.id) in filter_ids]
        if not repos:
            return {"contributors": []}

    # 3. Get GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    github_token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token required")

    # 4. Calculate period bounds
    period_start = get_period_start(period)
    since_str = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 5. Fetch commits from all repos in parallel
    github = GitHubReadOperations(github_token)
    fetch_limit = 200

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

    # 6. Flatten and filter errors
    all_commits: list[tuple[Repository, dict[str, Any]]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        all_commits.extend(result)

    # 7. Convert to TimelineEvent and filter by date
    events: list[TimelineEvent] = []
    for repo, commit in all_commits:
        timestamp = commit["commit"]["committer"]["date"]

        # Filter by period
        if timestamp < since_str:
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
        return {"contributors": []}

    # 8. Fetch commit stats for LOC calculation
    events = await _fetch_commit_stats(db, github, repos, events)

    # 9. Compute per-contributor details
    contributors = _compute_contributors(events, period, sort_by)

    return {"contributors": contributors}


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
        daily_activity = _generate_daily_activity(daily_counts, period)

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


# =============================================================================
# AI Summary Endpoints (Phase 3)
# =============================================================================


@dataclass
class AISummaryResponse:
    """Response structure for AI summary endpoint."""

    id: str | None
    period: str
    summary_text: str | None
    total_commits: int
    total_contributors: int
    total_additions: int
    total_deletions: int
    generated_at: str | None


@router.get("/products/{product_id}/ai-summary")
async def get_ai_summary(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get existing AI-generated summary for a product and period.

    Returns the stored summary if it exists, or {summary: null} if none.
    Does NOT generate a new summary - use POST /ai-summary/generate for that.
    """
    from app.domain import progress_summary_ops

    # Verify product access
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Fetch existing summary
    summary = await progress_summary_ops.get_by_product_period(db, product_id, period)

    if summary:
        return {
            "summary": {
                "id": str(summary.id),
                "period": summary.period,
                "summary_text": summary.summary_text,
                "total_commits": summary.total_commits,
                "total_contributors": summary.total_contributors,
                "total_additions": summary.total_additions,
                "total_deletions": summary.total_deletions,
                "generated_at": summary.generated_at.isoformat(),
            }
        }

    return {"summary": None}


@router.post("/products/{product_id}/ai-summary/generate")
async def generate_ai_summary(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Generate a new AI summary for a product's development progress.

    Fetches current progress data, generates a narrative summary using Claude,
    stores it in the database, and returns the result.

    This is a synchronous operation (typically 2-5 seconds) since Claude
    responses are fast enough that polling adds unnecessary complexity.
    """
    from app.domain import progress_summary_ops
    from app.services.progress.summarizer import ProgressData, progress_summarizer

    # Verify product access
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Get GitHub-linked repositories
    repos = await repository_ops.get_github_repos_by_product(db, product_id=product_id)
    if not repos:
        raise HTTPException(
            status_code=400,
            detail="No GitHub repositories linked to this product",
        )

    # Filter repositories if repo_ids provided
    if repo_ids:
        filter_ids = set(repo_ids.split(","))
        repos = [r for r in repos if str(r.id) in filter_ids]
        if not repos:
            raise HTTPException(
                status_code=400,
                detail="No matching repositories found",
            )

    # Get GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    github_token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token required")

    # Calculate period bounds
    period_start = get_period_start(period)
    since_str = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fetch commits from all repos in parallel
    github = GitHubReadOperations(github_token)
    fetch_limit = 200

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

    # Flatten and filter errors
    all_commits: list[tuple[Repository, dict[str, Any]]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        all_commits.extend(result)

    # Convert to TimelineEvent and filter by date
    events: list[TimelineEvent] = []
    for repo, commit in all_commits:
        timestamp = commit["commit"]["committer"]["date"]

        # Filter by period
        if timestamp < since_str:
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
        raise HTTPException(
            status_code=400,
            detail="No commits found in the selected period. Cannot generate summary.",
        )

    # Fetch commit stats for LOC calculation
    events = await _fetch_commit_stats(db, github, repos, events)

    # Compute summary data (reuse existing function)
    summary_data = _compute_summary(events, period)

    # Build ProgressData for the AI summarizer
    progress_data = ProgressData(
        period=period,
        total_commits=summary_data["total_commits"],
        total_contributors=summary_data["total_contributors"],
        total_additions=summary_data["total_additions"],
        total_deletions=summary_data["total_deletions"],
        focus_areas=summary_data["focus_areas"],
        top_contributors=summary_data["top_contributors"],
        recent_commits=summary_data["recent_commits"],
    )

    # Generate AI narrative
    try:
        narrative = await progress_summarizer.interpret(progress_data)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary: {str(e)}",
        ) from e

    # Store the summary
    stored_summary = await progress_summary_ops.upsert(
        db=db,
        product_id=product_id,
        period=period,
        summary_text=narrative.summary,
        total_commits=summary_data["total_commits"],
        total_contributors=summary_data["total_contributors"],
        total_additions=summary_data["total_additions"],
        total_deletions=summary_data["total_deletions"],
    )

    await db.commit()

    return {
        "summary": {
            "id": str(stored_summary.id),
            "period": stored_summary.period,
            "summary_text": stored_summary.summary_text,
            "total_commits": stored_summary.total_commits,
            "total_contributors": stored_summary.total_contributors,
            "total_additions": stored_summary.total_additions,
            "total_deletions": stored_summary.total_deletions,
            "generated_at": stored_summary.generated_at.isoformat(),
        }
    }


# =============================================================================
# Active Code Endpoint (Phase 5)
# =============================================================================


@dataclass
class FileActivity:
    """Activity stats for a single file."""

    path: str
    commits: int
    additions: int
    deletions: int


@dataclass
class DirectoryActivity:
    """Activity stats for a directory."""

    path: str
    commits: int
    additions: int
    deletions: int
    file_count: int


@dataclass
class ActiveCodeResponse:
    """Response structure for active code endpoint."""

    hottest_files: list[dict[str, Any]]
    directory_tree: list[dict[str, Any]]
    quiet_areas: list[dict[str, Any]]
    total_files_changed: int


@router.get("/products/{product_id}/active-code")
async def get_active_code(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get active code visualization data for a product.

    Returns file and directory activity including:
    - Hottest files (top 15 by commit count)
    - Directory tree with aggregated stats
    - Quiet areas (directories with no recent changes)
    - Total unique files changed
    """

    # 1. Verify product access
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # 2. Get GitHub-linked repositories
    repos = await repository_ops.get_github_repos_by_product(db, product_id=product_id)
    if not repos:
        return _empty_active_code_response()

    # 2b. Filter repositories if repo_ids provided
    if repo_ids:
        filter_ids = set(repo_ids.split(","))
        repos = [r for r in repos if str(r.id) in filter_ids]
        if not repos:
            return _empty_active_code_response()

    # 3. Get GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    github_token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token required")

    # 4. Calculate period bounds
    period_start = get_period_start(period)
    since_str = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 5. Fetch commits from all repos in parallel
    github = GitHubReadOperations(github_token)
    fetch_limit = 200

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

    # 6. Flatten and filter by date
    commits_in_period: list[tuple[Repository, dict[str, Any]]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        for repo, commit in result:
            timestamp = commit["commit"]["committer"]["date"]
            if timestamp >= since_str:
                commits_in_period.append((repo, commit))

    if not commits_in_period:
        return _empty_active_code_response()

    # 7. Fetch file details for each commit
    file_activity = await _fetch_file_activity(github, repos, commits_in_period)

    # 8. Compute active code data
    return _compute_active_code(file_activity)


async def _fetch_file_activity(
    github: GitHubReadOperations,
    repos: list[Repository],
    commits: list[tuple[Repository, dict[str, Any]]],
) -> dict[str, dict[str, int]]:
    """Fetch file changes for commits and aggregate by file path.

    Returns dict mapping file paths to {commits, additions, deletions}.
    """
    # Build repo map
    repo_map: dict[str, tuple[str, str]] = {}
    for repo in repos:
        if repo.full_name:
            owner_name, repo_name = repo.full_name.split("/")
            repo_map[repo.full_name] = (owner_name, repo_name)

    # Track file activity: path -> {commits, additions, deletions}
    file_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"commits": 0, "additions": 0, "deletions": 0}
    )

    # Fetch file changes with concurrency limit
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_STAT_FETCHES)

    async def fetch_commit_files(
        repo: Repository, commit: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        if not repo.full_name:
            return None
        repo_info = repo_map.get(repo.full_name)
        if not repo_info:
            return None
        owner_name, repo_name = repo_info
        sha = commit["sha"]

        async with semaphore:
            return await github.get_commit_files(owner_name, repo_name, sha)

    # Fetch all commit files in parallel
    tasks = [fetch_commit_files(repo, commit) for repo, commit in commits]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate file activity
    for i, result in enumerate(results):
        if isinstance(result, BaseException) or result is None:
            continue

        repo, _ = commits[i]
        repo_prefix = repo.name + "/" if repo.name else ""

        for file_change in result:
            # Prefix file path with repo name for multi-repo products
            file_path = repo_prefix + file_change.get("filename", "")
            if not file_path:
                continue

            file_stats[file_path]["commits"] += 1
            file_stats[file_path]["additions"] += file_change.get("additions", 0)
            file_stats[file_path]["deletions"] += file_change.get("deletions", 0)

    return dict(file_stats)


def _compute_active_code(
    file_activity: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """Compute active code visualization data from file activity."""

    if not file_activity:
        return _empty_active_code_response()

    # 1. Hottest files (top 15 by commit count)
    sorted_files = sorted(
        file_activity.items(),
        key=lambda x: (x[1]["commits"], x[1]["additions"] + x[1]["deletions"]),
        reverse=True,
    )
    hottest_files = [
        {
            "path": path,
            "commits": stats["commits"],
            "additions": stats["additions"],
            "deletions": stats["deletions"],
        }
        for path, stats in sorted_files[:15]
    ]

    # 2. Directory tree - aggregate by directory
    dir_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"commits": 0, "additions": 0, "deletions": 0, "files": set()}
    )

    for file_path, stats in file_activity.items():
        # Build directory hierarchy
        parts = file_path.split("/")

        # Aggregate to each parent directory level
        for i in range(1, len(parts)):
            dir_path = "/".join(parts[:i])
            dir_stats[dir_path]["commits"] += stats["commits"]
            dir_stats[dir_path]["additions"] += stats["additions"]
            dir_stats[dir_path]["deletions"] += stats["deletions"]
            dir_stats[dir_path]["files"].add(file_path)

    # Convert to list and sort by commits
    directory_tree = [
        {
            "path": path,
            "commits": stats["commits"],
            "additions": stats["additions"],
            "deletions": stats["deletions"],
            "file_count": len(stats["files"]),
            "depth": path.count("/"),
        }
        for path, stats in sorted(
            dir_stats.items(),
            key=lambda x: (x[1]["commits"], len(x[1]["files"])),
            reverse=True,
        )
    ]

    # 3. Quiet areas - top-level directories with no activity
    # Get all top-level directories from repos
    active_top_dirs = set()
    for file_path in file_activity:
        parts = file_path.split("/")
        if len(parts) > 1:
            active_top_dirs.add(parts[0])

    # For now, we don't have historical data to show "last changed X days ago"
    # So quiet_areas will just be empty or we can show low-activity directories
    # In Phase 8 (caching), we can track historical data
    quiet_areas: list[dict[str, Any]] = []

    return {
        "hottest_files": hottest_files,
        "directory_tree": directory_tree,
        "quiet_areas": quiet_areas,
        "total_files_changed": len(file_activity),
    }


def _empty_active_code_response() -> dict[str, Any]:
    """Return an empty active code response."""
    return {
        "hottest_files": [],
        "directory_tree": [],
        "quiet_areas": [],
        "total_files_changed": 0,
    }


# =============================================================================
# Velocity Endpoint (Phase 6)
# =============================================================================


@dataclass
class VelocityDataPoint:
    """Single data point for velocity charts."""

    date: str  # YYYY-MM-DD
    commits: int
    additions: int
    deletions: int
    contributors: int


@dataclass
class VelocityInsight:
    """A computed insight about development velocity."""

    type: str  # "trend", "peak", "pattern", "focus"
    message: str
    value: str | None = None


@router.get("/products/{product_id}/velocity")
async def get_velocity(
    product_id: uuid_pkg.UUID,
    period: str = Query("30d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
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

    # 1. Verify product access
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # 2. Get GitHub-linked repositories
    repos = await repository_ops.get_github_repos_by_product(db, product_id=product_id)
    if not repos:
        return _empty_velocity_response()

    # 2b. Filter repositories if repo_ids provided
    if repo_ids:
        filter_ids = set(repo_ids.split(","))
        repos = [r for r in repos if str(r.id) in filter_ids]
        if not repos:
            return _empty_velocity_response()

    # 3. Get GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    github_token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token required")

    # 4. Calculate period bounds (fetch extra for comparison)
    period_start = get_period_start(period)
    # Fetch 2x the period for comparison calculations
    extended_period = _get_extended_period(period)
    extended_start = get_period_start(extended_period)
    extended_since_str = extended_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 5. Fetch commits from all repos in parallel
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

    # 6. Flatten and filter errors
    all_commits: list[tuple[Repository, dict[str, Any]]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        all_commits.extend(result)

    # 7. Convert to TimelineEvent and filter by extended date range
    events: list[TimelineEvent] = []
    for repo, commit in all_commits:
        timestamp = commit["commit"]["committer"]["date"]

        # Filter by extended period (for comparison data)
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

    # 8. Fetch commit stats for LOC calculation
    events = await _fetch_commit_stats(db, github, repos, events)

    # 9. Compute velocity data
    return _compute_velocity(events, period, period_start)


def _get_extended_period(period: str) -> str:
    """Get an extended period string for fetching comparison data."""
    period_map = {
        "24h": "48h",
        "48h": "7d",
        "7d": "14d",
        "14d": "30d",
        "30d": "90d",
        "90d": "365d",
        "365d": "365d",  # Can't extend beyond a year easily
    }
    return period_map.get(period, "90d")


def _compute_velocity(
    events: list[TimelineEvent],
    period: str,
    period_start: datetime,
) -> dict[str, Any]:
    """Compute velocity data for charts and insights."""

    # Sort events by timestamp
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
        {
            "date": dp["date"],
            "additions": dp["additions"],
            "deletions": dp["deletions"],
        }
        for dp in velocity_data
    ]

    # Compute contributors over time
    contributors_data = [
        {
            "date": dp["date"],
            "contributors": dp["contributors"],
        }
        for dp in velocity_data
    ]

    # Compute insights
    insights = _compute_velocity_insights(
        velocity_data, current_totals, previous_totals, period
    )

    return {
        "velocity_data": velocity_data,
        "loc_data": loc_data,
        "contributors_data": contributors_data,
        "current_totals": current_totals,
        "previous_totals": previous_totals,
        "insights": insights,
    }


def _compute_daily_velocity(
    events: list[TimelineEvent], period: str
) -> list[dict[str, Any]]:
    """Compute daily velocity data points."""

    # Get period days
    period_days = {
        "24h": 1,
        "48h": 2,
        "7d": 7,
        "14d": 14,
        "30d": 30,
        "90d": 90,
        "365d": 365,
    }
    days = period_days.get(period, 30)

    # Initialize daily buckets
    today = datetime.now(timezone.utc).date()
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

    # Populate from events
    for event in events:
        date_str = event.timestamp.split("T")[0]
        if date_str in daily_data:
            daily_data[date_str]["commits"] += 1
            daily_data[date_str]["additions"] += event.additions or 0
            daily_data[date_str]["deletions"] += event.deletions or 0
            daily_data[date_str]["contributors"].add(event.commit_author)

    # Convert sets to counts and return as list
    result = []
    for date_str in sorted(daily_data.keys()):
        data = daily_data[date_str]
        result.append({
            "date": data["date"],
            "commits": data["commits"],
            "additions": data["additions"],
            "deletions": data["deletions"],
            "contributors": len(data["contributors"]),
        })

    return result


def _compute_period_totals(events: list[TimelineEvent]) -> dict[str, Any]:
    """Compute totals for a set of events."""

    if not events:
        return {
            "commits": 0,
            "additions": 0,
            "deletions": 0,
            "contributors": 0,
            "files_changed": 0,
        }

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
        if abs(change_pct) >= 5:  # Only show if significant
            direction = "up" if change_pct > 0 else "down"
            insights.append(
                VelocityInsight(
                    type="trend",
                    message=f"Velocity is {direction} {abs(change_pct):.0f}% compared to previous {period}",
                    value=f"{change_pct:+.0f}%",
                )
            )

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

        # Calculate averages
        day_averages = {
            day: day_totals[day] / day_counts[day]
            for day in day_totals
            if day_counts[day] > 0
        }

        if day_averages:
            busiest_day = max(day_averages, key=lambda d: day_averages[d])
            avg_commits = day_averages[busiest_day]
            if avg_commits >= 1:  # Only show if meaningful
                insights.append(
                    VelocityInsight(
                        type="pattern",
                        message=f"Busiest day: {busiest_day} (avg {avg_commits:.1f} commits)",
                        value=busiest_day,
                    )
                )

    # 4. Net code growth
    net_loc = current_totals["additions"] - current_totals["deletions"]
    if current_totals["additions"] + current_totals["deletions"] > 0:
        add_pct = (
            current_totals["additions"]
            / (current_totals["additions"] + current_totals["deletions"])
            * 100
        )
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
            insights.append(
                VelocityInsight(
                    type="pattern",
                    message=f"Average: {avg_overall:.1f} commits/day ({avg_per_active:.1f} on active days)",
                    value=f"{avg_overall:.1f}",
                )
            )

    return [asdict(i) for i in insights]


def _empty_velocity_response() -> dict[str, Any]:
    """Return an empty velocity response."""
    return {
        "velocity_data": [],
        "loc_data": [],
        "contributors_data": [],
        "current_totals": {
            "commits": 0,
            "additions": 0,
            "deletions": 0,
            "contributors": 0,
            "files_changed": 0,
        },
        "previous_totals": {
            "commits": 0,
            "additions": 0,
            "deletions": 0,
            "contributors": 0,
            "files_changed": 0,
        },
        "insights": [],
    }
