import uuid as uuid_pkg
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.backends import ECKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.config.plans import PlanConfig, get_plan
from app.core.database import get_db
from app.domain.organization_operations import organization_ops
from app.domain.subscription_operations import subscription_ops
from app.models.organization import Organization
from app.models.subscription import Subscription
from app.models.user import User

security = HTTPBearer(auto_error=False)

# Cache for JWKS to avoid fetching on every request
_jwks_cache: dict[str, Any] = {}


async def get_jwks() -> dict[str, Any]:
    """Fetch and cache JWKS from Supabase."""
    if _jwks_cache:
        return _jwks_cache

    async with httpx.AsyncClient() as client:
        response = await client.get(settings.supabase_jwks_url)
        response.raise_for_status()
        jwks = response.json()
        _jwks_cache.update(jwks)
        return jwks


def get_signing_key(jwks: dict[str, Any], token: str) -> ECKey:
    """Get the signing key from JWKS that matches the token's kid."""
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return ECKey(key, algorithm="ES256")

    raise ValueError("Unable to find matching key in JWKS")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate Supabase JWT and return current user.

    Creates user record on first API call if not exists.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = credentials.credentials

    try:
        jwks = await get_jwks()
        signing_key = get_signing_key(jwks, token)

        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["ES256"],
            audience="authenticated",
        )
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )
        user_id = uuid_pkg.UUID(user_id_str)
    except (JWTError, ValueError, httpx.HTTPError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from None

    # Get or create user
    statement = select(User).where(User.id == user_id)
    result = await db.execute(statement)
    user = result.scalar_one_or_none()

    # Extract metadata for potential user/org creation
    app_metadata = payload.get("app_metadata", {})
    user_metadata = payload.get("user_metadata", {})

    if not user:
        # Create user on first API call (fallback if trigger didn't run)
        auth_provider = app_metadata.get("provider", "email")

        user = User(
            id=user_id,
            email=payload.get("email"),
            github_username=user_metadata.get("user_name"),
            avatar_url=user_metadata.get("avatar_url"),
            auth_provider=auth_provider,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)

    # Check if user has an organization (may be missing for manually-created users)
    user_orgs = await organization_ops.get_for_user(db, user.id)
    if not user_orgs:
        # Create personal organization (handles users created before trigger extension)
        display_name = user_metadata.get("full_name") or user_metadata.get("name")
        await organization_ops.create_personal_org(
            db,
            user_id=user.id,
            user_name=display_name,
            user_email=user.email,
        )

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Get current user if authenticated, None otherwise."""
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def get_current_organization(
    org_id: uuid_pkg.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """
    Get the current organization context.

    Resolution order:
    1. If org_id is provided (query param), use that org (must be a member)
    2. Otherwise, use the user's first/default organization

    Raises 403 if user is not a member of the requested organization.
    Raises 404 if no organization found.
    """
    if org_id:
        # Check if user is a member of the specified organization
        is_member = await organization_ops.is_member(db, org_id, current_user.id)
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this organization",
            )
        org = await organization_ops.get(db, org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )
        return org

    # Default to user's first organization (personal workspace)
    orgs = await organization_ops.get_for_user(db, current_user.id)
    if not orgs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No organization found for user",
        )

    return orgs[0]


async def require_org_admin(
    current_user: User = Depends(get_current_user),
    current_org: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """
    Require the current user to be an admin or owner of the current organization.

    Returns the organization if authorized, raises 403 otherwise.
    """
    from app.models.organization import MemberRole

    role = await organization_ops.get_member_role(db, current_org.id, current_user.id)
    if role not in (MemberRole.OWNER.value, MemberRole.ADMIN.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or owner access required",
        )
    return current_org


async def require_org_owner(
    current_user: User = Depends(get_current_user),
    current_org: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """
    Require the current user to be an owner of the current organization.

    Returns the organization if authorized, raises 403 otherwise.
    """
    from app.models.organization import MemberRole

    role = await organization_ops.get_member_role(db, current_org.id, current_user.id)
    if role != MemberRole.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner access required",
        )
    return current_org


async def require_system_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Require the current user to be a system admin.

    Returns the user if authorized, raises 403 otherwise.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System admin access required",
        )
    return current_user


# ---------------------------------------------------------------------------
# Feature Gating Dependencies
# ---------------------------------------------------------------------------


@dataclass
class SubscriptionContext:
    """Context containing organization, subscription, and plan configuration."""

    organization: Organization
    subscription: Subscription
    plan: PlanConfig


async def get_subscription_context(
    current_org: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionContext:
    """
    Get the subscription context for the current organization.

    Returns org, subscription, and plan config for feature checks.
    """
    subscription = await subscription_ops.get_by_org(db, current_org.id)

    if not subscription:
        # Shouldn't happen if org was created properly, but handle gracefully
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Organization subscription not found",
        )

    plan = get_plan(subscription.plan_tier)

    return SubscriptionContext(
        organization=current_org,
        subscription=subscription,
        plan=plan,
    )


class FeatureGate:
    """
    Dependency class for feature gating based on subscription plan.

    Usage:
        @router.post("/some-feature")
        async def some_feature(
            _: bool = Depends(FeatureGate("drift_detection")),
            ...
        ):
            # Only accessible if plan has drift_detection feature
            ...
    """

    def __init__(self, feature: str):
        self.feature = feature

    async def __call__(
        self,
        ctx: SubscriptionContext = Depends(get_subscription_context),
    ) -> bool:
        """Check if the feature is enabled for the current organization's plan."""
        has_feature = getattr(ctx.plan, self.feature, False)

        if not has_feature:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Feature '{self.feature}' requires a higher plan. "
                f"Current plan: {ctx.plan.display_name}",
            )

        return True


async def require_agent_enabled(
    ctx: SubscriptionContext = Depends(get_subscription_context),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionContext:
    """
    Require that agent features are enabled for the organization.

    For free tier: Checks if org is within repo limit.
    For paid tiers: Always enabled.

    Returns the subscription context if agent is enabled.
    """
    from app.domain.repository_operations import repository_ops

    # Count current repos for the org
    repo_count = await repository_ops.count_by_org(db, ctx.organization.id)

    is_enabled = await subscription_ops.is_agent_enabled(db, ctx.organization.id, repo_count)

    if not is_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Agent disabled. You have {repo_count} repositories but your "
            f"{ctx.plan.display_name} plan only allows {ctx.plan.base_repo_limit}. "
            "Remove repositories or upgrade to re-enable.",
        )

    return ctx
