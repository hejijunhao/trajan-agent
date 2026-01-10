"""
Stats Extractor service for aggregating repository statistics.

This service extracts and aggregates factual statistics from GitHub data
without any LLM involvement. All data comes directly from GitHub API responses.

Part of the Analysis Agent refactoring (Phase 2).
"""

from datetime import UTC, datetime

from app.schemas.product_overview import ContributorStat, LanguageStat, OverviewStats
from app.services.github import RepoContext, calculate_lines_of_code


def _parse_iso_date(date_str: str | None) -> datetime | None:
    """Parse an ISO 8601 date string to datetime, handling None."""
    if not date_str:
        return None
    try:
        # Handle both 'Z' suffix and '+00:00' formats
        if date_str.endswith("Z"):
            date_str = date_str[:-1] + "+00:00"
        return datetime.fromisoformat(date_str)
    except ValueError:
        return None


def _format_date_iso(dt: datetime | None) -> str | None:
    """Format a datetime as ISO date (YYYY-MM-DD)."""
    if not dt:
        return None
    return dt.strftime("%Y-%m-%d")


def _format_relative_time(dt: datetime | None) -> str | None:
    """Format a datetime as human-readable relative time."""
    if not dt:
        return None

    now = datetime.now(UTC)
    # Ensure dt is timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    diff = now - dt

    seconds = diff.total_seconds()
    if seconds < 0:
        return "just now"

    minutes = seconds / 60
    hours = minutes / 60
    days = hours / 24
    weeks = days / 7
    months = days / 30
    years = days / 365

    if seconds < 60:
        return "just now"
    elif minutes < 60:
        n = int(minutes)
        return f"{n} minute{'s' if n != 1 else ''} ago"
    elif hours < 24:
        n = int(hours)
        return f"{n} hour{'s' if n != 1 else ''} ago"
    elif days < 7:
        n = int(days)
        return f"{n} day{'s' if n != 1 else ''} ago"
    elif weeks < 4:
        n = int(weeks)
        return f"{n} week{'s' if n != 1 else ''} ago"
    elif months < 12:
        n = int(months)
        return f"{n} month{'s' if n != 1 else ''} ago"
    else:
        n = int(years)
        return f"{n} year{'s' if n != 1 else ''} ago"


class StatsExtractor:
    """
    Extract factual statistics from GitHub data without LLM.

    This service aggregates statistics from multiple repositories into
    a single OverviewStats object. All data comes from GitHub API —
    no estimation or generation.
    """

    def extract_stats(self, repo_contexts: list[RepoContext]) -> OverviewStats:
        """
        Aggregate statistics from multiple repositories.

        Args:
            repo_contexts: List of RepoContext objects with GitHub data

        Returns:
            OverviewStats with aggregated data from all repositories
        """
        if not repo_contexts:
            return OverviewStats()

        # Aggregate basic counts
        total_stars = sum(ctx.stars_count for ctx in repo_contexts)
        total_forks = sum(ctx.forks_count for ctx in repo_contexts)
        total_open_issues = sum(ctx.open_issues_count for ctx in repo_contexts)

        # Find timeline boundaries (filter out None from parse failures)
        created_dates = [
            dt
            for ctx in repo_contexts
            if ctx.created_at and (dt := _parse_iso_date(ctx.created_at)) is not None
        ]
        pushed_dates = [
            dt
            for ctx in repo_contexts
            if ctx.pushed_at and (dt := _parse_iso_date(ctx.pushed_at)) is not None
        ]

        earliest_created = min(created_dates) if created_dates else None
        latest_pushed = max(pushed_dates) if pushed_dates else None

        # Aggregate commit stats
        first_commit_dates: list[datetime] = []
        last_commit_dates: list[datetime] = []
        total_commits = 0

        for ctx in repo_contexts:
            if ctx.commit_stats:
                total_commits += ctx.commit_stats.total_commits
                if ctx.commit_stats.first_commit_date:
                    dt = _parse_iso_date(ctx.commit_stats.first_commit_date)
                    if dt:
                        first_commit_dates.append(dt)
                if ctx.commit_stats.last_commit_date:
                    dt = _parse_iso_date(ctx.commit_stats.last_commit_date)
                    if dt:
                        last_commit_dates.append(dt)

        earliest_first_commit = min(first_commit_dates) if first_commit_dates else None
        latest_last_commit = max(last_commit_dates) if last_commit_dates else None

        # Count total files from trees
        total_files = sum(len(ctx.tree.files) if ctx.tree else 0 for ctx in repo_contexts)

        # Calculate lines of code from fetched files
        total_loc = sum(calculate_lines_of_code(ctx.files) for ctx in repo_contexts)

        # Get license from first repo that has one
        license_name: str | None = None
        for ctx in repo_contexts:
            if ctx.license_name:
                license_name = ctx.license_name
                break

        # Get default branch from first repo
        default_branch: str | None = None
        if repo_contexts:
            default_branch = repo_contexts[0].default_branch

        # Merge contributors across repos
        contributors = self._merge_contributors(repo_contexts)
        contributor_count = len(contributors)
        top_contributors = contributors[:10]  # Top 10

        # Merge languages across repos
        languages = self._merge_languages(repo_contexts)

        return OverviewStats(
            # Timeline
            project_created=_format_date_iso(earliest_created),
            first_commit=_format_date_iso(earliest_first_commit),
            last_commit=_format_date_iso(latest_last_commit),
            last_activity=_format_relative_time(latest_pushed),
            # Code metrics
            total_lines_of_code=total_loc if total_loc > 0 else None,
            total_files=total_files if total_files > 0 else None,
            total_commits=total_commits if total_commits > 0 else None,
            # Repository info
            repo_count=len(repo_contexts),
            default_branch=default_branch,
            license=license_name,
            # Activity (issues & PRs) - we only have open_issues from repo metadata
            open_issues=total_open_issues if total_open_issues > 0 else None,
            closed_issues=None,  # Would require separate API call
            open_prs=None,  # Would require separate API call
            merged_prs=None,  # Would require separate API call
            # GitHub stats
            stars=total_stars,
            forks=total_forks,
            watchers=0,  # Not currently fetched
            # People
            contributor_count=contributor_count,
            top_contributors=top_contributors,
            # Languages
            languages=languages,
            # Deployment - not available from GitHub API
            domains=[],
            environments=[],
        )

    def _merge_contributors(self, repo_contexts: list[RepoContext]) -> list[ContributorStat]:
        """
        Merge contributors across multiple repositories.

        Contributors are merged by login (username). Commit counts are summed
        for contributors who appear in multiple repos.

        Returns:
            List of ContributorStat sorted by commits (descending)
        """
        # Use dict to merge by login
        merged: dict[str, ContributorStat] = {}

        for ctx in repo_contexts:
            for contrib in ctx.contributors:
                login = contrib.login
                if login in merged:
                    # Add commits to existing contributor
                    existing = merged[login]
                    merged[login] = ContributorStat(
                        name=existing.name,
                        commits=existing.commits + contrib.contributions,
                        avatar=existing.avatar or contrib.avatar_url,
                    )
                else:
                    merged[login] = ContributorStat(
                        name=login,
                        commits=contrib.contributions,
                        avatar=contrib.avatar_url,
                    )

        # Sort by commits descending
        sorted_contributors = sorted(merged.values(), key=lambda c: c.commits, reverse=True)
        return sorted_contributors

    def _merge_languages(self, repo_contexts: list[RepoContext]) -> list[LanguageStat]:
        """
        Merge language statistics across multiple repositories.

        Languages are merged by name. Byte counts are summed and percentages
        are recalculated based on the total.

        Returns:
            List of LanguageStat sorted by percentage (descending)
        """
        # Aggregate bytes by language name
        language_bytes: dict[str, int] = {}
        language_colors: dict[str, str] = {}

        for ctx in repo_contexts:
            for lang in ctx.languages:
                name = lang.name
                if name in language_bytes:
                    language_bytes[name] += lang.bytes
                else:
                    language_bytes[name] = lang.bytes
                    language_colors[name] = lang.color

        if not language_bytes:
            return []

        # Calculate total and percentages
        total_bytes = sum(language_bytes.values())
        if total_bytes == 0:
            return []

        languages = [
            LanguageStat(
                name=name,
                percentage=round((byte_count / total_bytes) * 100, 1),
                color=language_colors[name],
            )
            for name, byte_count in language_bytes.items()
        ]

        # Sort by percentage descending
        languages.sort(key=lambda x: x.percentage, reverse=True)
        return languages
