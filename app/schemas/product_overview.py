"""Pydantic schemas for the AI-generated product overview.

These schemas define the structure of the `product_overview` JSONB column
in the products table. They serve as:
1. Validation - Ensure Claude's response matches expected shape
2. Type safety - Frontend knows exactly what to expect
3. Documentation - Self-documenting API contract

Field naming uses snake_case (Python convention). The frontend TypeScript
types mirror this structure.
"""

from datetime import datetime

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────
# Stats Sub-Models
# ─────────────────────────────────────────────────────────────


class LanguageStat(BaseModel):
    """Programming language usage statistics."""

    name: str = Field(description="Language name, e.g., 'TypeScript'")
    percentage: float = Field(description="Percentage of codebase (0-100)")
    color: str = Field(description="Hex color for visualization, e.g., '#3178c6'")


class ContributorStat(BaseModel):
    """Top contributor statistics."""

    name: str = Field(description="GitHub username or display name")
    commits: int = Field(description="Number of commits")
    avatar: str | None = Field(default=None, description="Avatar URL")


class OverviewStats(BaseModel):
    """Comprehensive project statistics.

    All fields are optional to handle partial data from GitHub API.
    """

    # Timeline
    project_created: str | None = Field(
        default=None, description="ISO date (YYYY-MM-DD) when project was created"
    )
    first_commit: str | None = Field(default=None, description="ISO date of first commit")
    last_commit: str | None = Field(default=None, description="ISO date of most recent commit")
    last_activity: str | None = Field(
        default=None, description="Human-readable relative time, e.g., '2 hours ago'"
    )
    last_activity_at: str | None = Field(
        default=None, description="ISO 8601 datetime of most recent push for client-side formatting"
    )

    # Code metrics
    total_lines_of_code: int | None = Field(default=None, description="Total LOC across all repos")
    total_files: int | None = Field(default=None, description="Total file count")
    total_commits: int | None = Field(default=None, description="Total commit count")

    # Repository info
    repo_count: int = Field(default=0, description="Number of linked repositories")
    default_branch: str | None = Field(default=None, description="Primary branch name")
    license: str | None = Field(default=None, description="License identifier, e.g., 'MIT'")

    # Activity (issues & PRs)
    open_issues: int | None = Field(default=None, description="Open issues count")
    closed_issues: int | None = Field(default=None, description="Closed issues count")
    open_prs: int | None = Field(default=None, description="Open PRs count")
    merged_prs: int | None = Field(default=None, description="Merged PRs count")

    # GitHub stats
    stars: int = Field(default=0, description="Total stars across repos")
    forks: int = Field(default=0, description="Total forks across repos")
    watchers: int = Field(default=0, description="Total watchers across repos")

    # People
    contributor_count: int = Field(default=0, description="Number of unique contributors")
    top_contributors: list[ContributorStat] = Field(
        default_factory=list, description="Top contributors by commit count"
    )

    # Languages
    languages: list[LanguageStat] = Field(
        default_factory=list, description="Language breakdown with percentages"
    )

    # Deployment
    domains: list[str] = Field(
        default_factory=list, description="Deployed domains, e.g., ['app.example.com']"
    )
    environments: list[str] = Field(
        default_factory=list, description="Environment names, e.g., ['production', 'staging']"
    )


# ─────────────────────────────────────────────────────────────
# Architecture Sub-Models
# ─────────────────────────────────────────────────────────────


class ApiEndpoint(BaseModel):
    """API endpoint definition."""

    method: str = Field(description="HTTP method: GET, POST, PATCH, PUT, DELETE")
    path: str = Field(description="API path, e.g., '/api/v1/products'")
    description: str = Field(description="Brief description of what the endpoint does")


class DatabaseModel(BaseModel):
    """Database model/table definition."""

    name: str = Field(description="Model name, e.g., 'User'")
    fields: list[str] = Field(description="List of key field names")


class ServiceInfo(BaseModel):
    """Service or module definition."""

    name: str = Field(description="Service name, e.g., 'GitHubService'")
    description: str = Field(description="What the service does")


class FrontendPage(BaseModel):
    """Frontend page/route definition."""

    path: str = Field(description="Route path, e.g., '/dashboard'")
    name: str = Field(description="Page name, e.g., 'Dashboard'")
    description: str = Field(description="What the page shows")


class OverviewArchitecture(BaseModel):
    """Structured architecture data for the Architecture Visualizer component."""

    api_endpoints: list[ApiEndpoint] = Field(
        default_factory=list, description="List of API endpoints"
    )
    database_models: list[DatabaseModel] = Field(
        default_factory=list, description="List of database models"
    )
    services: list[ServiceInfo] = Field(
        default_factory=list, description="List of services/modules"
    )
    frontend_pages: list[FrontendPage] = Field(
        default_factory=list, description="List of frontend pages"
    )


# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────


class OverviewSummary(BaseModel):
    """High-level project summary."""

    one_liner: str = Field(description="Single compelling sentence (max 150 chars)")
    introduction: str = Field(description="2-3 paragraph overview with markdown formatting")
    status: str = Field(
        default="active", description="Project status: active, maintenance, archived, deprecated"
    )


# ─────────────────────────────────────────────────────────────
# Main ProductOverview Schema
# ─────────────────────────────────────────────────────────────


class ProductOverview(BaseModel):
    """Complete product overview generated by the analysis agent.

    This schema defines the shape of the `product_overview` JSONB column.

    Structure rationale:
    - `summary`: High-level project description (one-liner + intro)
    - `stats`: Quantitative metrics from GitHub API + code analysis
    - `*_content` fields: Freeform markdown for each deep-dive section
    - `architecture`: Structured data for the Architecture Visualizer component
    - Metadata: When analysis ran and which model was used
    """

    # Summary section
    summary: OverviewSummary = Field(description="High-level project summary")

    # Quantitative stats
    stats: OverviewStats = Field(description="Project statistics and metrics")

    # Deep dive content (Markdown) - each maps to a sub-tab in the frontend
    technical_content: str = Field(description="Technical blueprint markdown")
    business_content: str = Field(description="Business overview markdown")
    features_content: str = Field(description="Key features markdown")
    use_cases_content: str = Field(description="Use cases markdown")

    # Structured architecture data (used by Architecture Visualizer component)
    architecture: OverviewArchitecture = Field(description="Structured architecture visualization")

    # Metadata
    analyzed_at: datetime = Field(description="When analysis was completed")
    analyzer_model: str = Field(
        default="claude-sonnet-4-20250514", description="Model used for analysis"
    )


# ─────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────


class AnalyzeProductResponse(BaseModel):
    """Response from triggering product analysis."""

    status: str = Field(description="'analyzing' | 'already_analyzing'")
    message: str = Field(description="Human-readable status message")
