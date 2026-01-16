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
