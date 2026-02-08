"""Type definitions for Progress API responses."""

from dataclasses import dataclass
from typing import Any


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
    last_activity_at: str | None


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


@dataclass
class ProductShippedSummary:
    """Shipped summary for a single product in the dashboard."""

    product_id: str
    product_name: str
    product_color: str | None
    items: list[dict[str, str]]  # [{description, category}]
    has_significant_changes: bool
    total_commits: int
    total_additions: int
    total_deletions: int
    generated_at: str | None
    last_activity_at: str | None
