"""API key authentication dependencies for public endpoints.

Validates API keys from Authorization: Bearer trj_pk_xxx headers
and enforces scope-based access control.
"""

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domain.product_api_key_operations import ProductApiKeyOperations, api_key_ops
from app.models.product_api_key import ProductApiKey

api_key_security = HTTPBearer(auto_error=False)


async def get_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(api_key_security),
    db: AsyncSession = Depends(get_db),
) -> ProductApiKey:
    """Validate API key from Bearer token and return the key record.

    Uses plain get_db (no RLS) — public endpoints scope by api_key.product_id.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )

    api_key = await api_key_ops.validate_key(db, credentials.credentials)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
        )

    return api_key


def require_scope(scope: str) -> Callable[..., Awaitable[ProductApiKey]]:
    """Return a dependency that validates an API key has the required scope."""

    async def _check_scope(
        api_key: ProductApiKey = Depends(get_api_key),
    ) -> ProductApiKey:
        if not ProductApiKeyOperations.check_scope(api_key, scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key missing required scope: {scope}",
            )
        return api_key

    return _check_scope
