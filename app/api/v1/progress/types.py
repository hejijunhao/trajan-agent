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
class LeaderboardEntry:
    """A single contributor entry in the leaderboard."""

    rank: int
    author: str
    avatar_url: str | None
    commits: int
    additions: int
    deletions: int
    net_loc: int
    files_changed: int
    repos_contributed_to: int
    active_days: int
    avg_commits_per_active_day: float
    daily_activity: list[dict[str, Any]]
    period_days: int


@dataclass
class CommitTypeBreakdown:
    """Breakdown of commits by conventional type."""

    type: str
    count: int
    percentage: float


@dataclass
class CommitQuality:
    """Aggregate commit quality metrics."""

    commit_types: list[dict[str, Any]]
    avg_commit_size_loc: int
    avg_files_per_commit: float
    large_commits: int
    conventional_commit_pct: float
    total_analyzed: int


@dataclass
class HeatmapRow:
    """A single contributor's row in the activity heatmap."""

    author: str
    avatar_url: str | None
    cells: list[dict[str, Any]]  # [{date, commits}]


@dataclass
class DayOfWeekEntry:
    """Commit count for a single day of the week."""

    day: str  # "Mon", "Tue", ...
    commits: int


@dataclass
class RepoComparison:
    """Per-repository comparison stats for the velocity tab."""

    repository_name: str
    repository_full_name: str
    commits: int
    additions: int
    deletions: int
    net_loc: int
    contributors: int
    bus_factor: int
    churn_ratio: float
    cadence: str  # "daily" | "sporadic" | "inactive"
    active_days: int


@dataclass
class PulseData:
    """Development pulse metrics for the summary card."""

    velocity_trend: float  # % change vs previous period
    velocity_label: str  # "faster" | "slower" | "steady"
    team_streak_days: int  # consecutive days with ≥1 commit
    active_days_in_period: int  # days with commits in this period
    period_days: int  # total days in period


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
