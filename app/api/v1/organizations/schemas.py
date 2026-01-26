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
