"""JWT validation and user authentication dependencies."""

import uuid as uuid_pkg
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.backends import ECKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.domain.organization_operations import organization_ops
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
