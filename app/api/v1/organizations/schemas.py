"""Response schemas for organization API endpoints."""

from typing import Any

from pydantic import BaseModel


class OrganizationResponse(BaseModel):
    """Organization response with basic info."""

    id: str
    name: str
    slug: str
    owner_id: str
    created_at: str
    updated_at: str | None
    is_personal: bool  # True if user is owner and it's their first org
    role: str  # User's role in this org


class OrganizationDetailResponse(BaseModel):
    """Detailed organization response with members and subscription."""

    id: str
    name: str
    slug: str
    owner_id: str
    settings: dict[str, Any] | None
    created_at: str
    updated_at: str | None
    role: str  # User's role in this org
    member_count: int


class MemberResponse(BaseModel):
    """Organization member response."""

    id: str
    user_id: str
    email: str
    display_name: str | None
    avatar_url: str | None
    role: str
    joined_at: str
    invited_by: str | None
    invited_at: str | None
    has_signed_in: bool  # True if user has completed onboarding (reliable pending detection)


class SubscriptionResponse(BaseModel):
    """Subscription response for organization."""

    id: str
    plan_tier: str
    plan_display_name: str
    status: str
    base_repo_limit: int
    is_manually_assigned: bool
    created_at: str
    # Plan features
    features: dict[str, bool]
    analysis_frequency: str
    price_monthly: int
    allows_overages: bool
    overage_repo_price: int
    # Cancellation fields
    cancel_at_period_end: bool
    current_period_end: str | None


class PlanResponse(BaseModel):
    """Plan information for frontend display."""

    tier: str
    display_name: str
    price_monthly: int
    base_repo_limit: int
    overage_repo_price: int
    allows_overages: bool
    features: dict[str, bool]
    analysis_frequency: str


# --- Ownership Transfer Schemas ---


class OwnershipTransferRequest(BaseModel):
    """Request to transfer organization ownership to an existing member."""

    new_owner_id: str  # UUID of existing member to become new owner


class OwnershipTransferResponse(BaseModel):
    """Response after successful ownership transfer."""

    id: str
    name: str
    slug: str
    owner_id: str  # New owner's ID
    previous_owner_id: str  # Previous owner's ID
    message: str


# --- Organization Repository Schemas ---


class OrgRepositoryResponse(BaseModel):
    """Repository response with product context for downgrade selection."""

    id: str
    name: str
    full_name: str | None
    description: str | None
    default_branch: str | None
    product_id: str
    product_name: str
    updated_at: str | None


class OrgRepositoriesListResponse(BaseModel):
    """List of repositories across all products in an organization."""

    repositories: list[OrgRepositoryResponse]
    total_count: int


# --- Repo Limit Status Schemas ---


class RepoLimitStatusResponse(BaseModel):
    """Repository limit status for overage confirmation UI."""

    current_count: int  # Current number of repos in the organization
    base_limit: int  # Repos included in plan
    allows_overages: bool  # Whether plan allows adding beyond limit
    overage_price_cents: int  # Cost per additional repo (e.g., 1000 = $10)


# --- Team Activity Schemas ---


class TeamMemberProduct(BaseModel):
    """Per-product commit breakdown for a team member."""

    product_id: str
    product_name: str
    commits: int


class TeamMemberStats(BaseModel):
    """Aggregated stats for a team member across all products."""

    commits: int
    additions: int
    deletions: int
    files_changed: int
    last_active: str | None
    streak_days: int
    daily_activity: list[dict[str, Any]]
    focus_areas: list[str]
    products: list[TeamMemberProduct]


class TeamMemberRecentCommit(BaseModel):
    """A recent commit with product context."""

    sha: str
    message: str
    repository: str
    product_name: str
    timestamp: str
    url: str | None


class TeamMember(BaseModel):
    """A team member with activity data."""

    user_id: str | None  # None for external contributors (GitHub-only)
    display_name: str
    email: str | None
    avatar_url: str | None
    role: str | None  # None for external contributors
    joined_at: str | None
    status: str  # "active" | "idle" | "pending"
    stats: TeamMemberStats | None  # None for pending invites
    recent_commits: list[TeamMemberRecentCommit]


class TeamActivityAggregate(BaseModel):
    """Summary stats for the team activity response."""

    active_contributors: int
    total_commits: int
    total_additions: int
    total_deletions: int
    products_touched: int


class TeamActivityResponse(BaseModel):
    """Response for the team activity endpoint."""

    period_days: int
    aggregate: TeamActivityAggregate
    members: list[TeamMember]
