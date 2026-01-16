"""Product access control dependencies."""

import uuid as uuid_pkg
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domain.organization_operations import organization_ops
from app.domain.product_access_operations import product_access_ops
from app.domain.product_operations import product_ops
from app.models.user import User

from .auth import get_current_user


@dataclass
class ProductAccessContext:
    """Context containing product access information."""

    product_id: uuid_pkg.UUID
    user_id: uuid_pkg.UUID
    access_level: str  # 'admin', 'editor', 'viewer', 'none'


async def get_product_access(
    product_id: uuid_pkg.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductAccessContext:
    """
    Get current user's access level for a product.

    Raises 404 if product not found.
    Raises 403 if user is not a member of the product's organization.
    Raises 403 if user has no access to this product.
    """
    # Get product to find its organization
    product = await product_ops.get(db, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Get user's org role
    if not product.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Product is not associated with an organization",
        )
    org_role = await organization_ops.get_member_role(db, product.organization_id, current_user.id)
    if not org_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    # Get effective access level
    access_level = await product_access_ops.get_effective_access(
        db, product_id, current_user.id, org_role
    )

    if access_level == "none":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this project",
        )

    return ProductAccessContext(
        product_id=product_id,
        user_id=current_user.id,
        access_level=access_level,
    )


async def require_product_editor(
    access_ctx: ProductAccessContext = Depends(get_product_access),
) -> ProductAccessContext:
    """Require editor or admin access to a product."""
    if access_ctx.access_level not in ("admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Editor access required",
        )
    return access_ctx


async def require_product_admin(
    access_ctx: ProductAccessContext = Depends(get_product_access),
) -> ProductAccessContext:
    """Require admin access to a product."""
    if access_ctx.access_level != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return access_ctx


async def require_variables_access(
    access_ctx: ProductAccessContext = Depends(get_product_access),
) -> ProductAccessContext:
    """
    Require access to Variables tab (editor or admin only).

    Viewers cannot access environment variables.
    """
    if access_ctx.access_level not in ("admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to environment variables. "
            "Please contact your project Admin to request Editor access.",
        )
    return access_ctx


# ---------------------------------------------------------------------------
# Standalone access check functions (for use outside dependency injection)
# ---------------------------------------------------------------------------


async def _check_product_access(
    db: AsyncSession,
    product_id: uuid_pkg.UUID,
    user_id: uuid_pkg.UUID,
    required_level: Literal["admin", "editor", "viewer"],
) -> None:
    """
    Check if user has the required access level to a product.

    Args:
        db: Database session
        product_id: The product UUID
        user_id: The user UUID
        required_level: Minimum required access level ('admin', 'editor', or 'viewer')

    Raises:
        HTTPException 404 if product not found
        HTTPException 403 if user doesn't have required access
    """
    product = await product_ops.get(db, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if not product.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Product is not associated with an organization",
        )

    org_role = await organization_ops.get_member_role(db, product.organization_id, user_id)
    if not org_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    access_level = await product_access_ops.get_effective_access(db, product_id, user_id, org_role)

    # Check access based on required level
    if required_level == "admin":
        if access_level != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required for this action.",
            )
    elif required_level == "editor":
        if access_level not in ("admin", "editor"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Editor access required. You have view-only access to this project.",
            )
    elif required_level == "viewer" and access_level == "none":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this project",
        )


async def check_product_editor_access(
    db: AsyncSession,
    product_id: uuid_pkg.UUID,
    user_id: uuid_pkg.UUID,
) -> None:
    """
    Check if user has editor (or higher) access to a product.

    Raises 403 if user doesn't have edit access.
    Use this for mutation endpoints (create, update, delete).
    """
    await _check_product_access(db, product_id, user_id, "editor")


async def check_product_admin_access(
    db: AsyncSession,
    product_id: uuid_pkg.UUID,
    user_id: uuid_pkg.UUID,
) -> None:
    """
    Check if user has admin access to a product.

    Raises 403 if user doesn't have admin access.
    Use this for admin-only operations (delete project, manage collaborators).
    """
    await _check_product_access(db, product_id, user_id, "admin")
