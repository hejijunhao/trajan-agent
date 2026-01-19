"""Quick Access API - password-protected shareable links to product App Info."""

import uuid as uuid_pkg
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.api.deps import get_current_user
from app.config import settings
from app.core.database import get_db
from app.core.rate_limit import REVEAL_LIMIT, rate_limiter
from app.domain import app_info_ops, product_ops
from app.domain.organization_operations import organization_ops
from app.domain.product_access_operations import product_access_ops
from app.models.organization import MemberRole
from app.models.product import Product
from app.models.user import User

router = APIRouter(prefix="/quick-access", tags=["quick-access"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class QuickAccessStatus(SQLModel):
    """Response schema for quick access status."""

    enabled: bool
    url: str | None = None
    created_at: datetime | None = None
    created_by_name: str | None = None


class QuickAccessProductInfo(SQLModel):
    """Response schema for product info accessed via quick access token."""

    product_id: uuid_pkg.UUID
    product_name: str
    organization_name: str


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def build_quick_access_url(token: str) -> str:
    """Build the full quick access URL from a token."""
    return f"{settings.frontend_url}/quick-access/{token}"


async def get_product_for_quick_access_management(
    product_id: uuid_pkg.UUID,
    current_user: User,
    db: AsyncSession,
) -> Product:
    """Get a product and verify user has access to manage quick access."""
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    return product


async def get_creator_name(db: AsyncSession, user_id: uuid_pkg.UUID | None) -> str | None:
    """Get the display name of the user who created quick access."""
    if not user_id:
        return None
    statement = select(User).where(User.id == user_id)  # type: ignore[arg-type]
    result = await db.execute(statement)
    user = result.scalar_one_or_none()
    if user:
        return user.display_name or user.email
    return None


# ---------------------------------------------------------------------------
# Management Endpoints (require org admin for the product's organization)
# ---------------------------------------------------------------------------


@router.get("/products/{product_id}", response_model=QuickAccessStatus)
async def get_quick_access_status(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuickAccessStatus:
    """Get the quick access status for a product."""
    product = await get_product_for_quick_access_management(product_id, current_user, db)

    creator_name = await get_creator_name(db, product.quick_access_created_by)

    return QuickAccessStatus(
        enabled=product.quick_access_enabled,
        url=build_quick_access_url(product.quick_access_token)
        if product.quick_access_token
        else None,
        created_at=product.quick_access_created_at,
        created_by_name=creator_name,
    )


@router.post("/products/{product_id}/enable", response_model=QuickAccessStatus)
async def enable_quick_access(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuickAccessStatus:
    """Enable quick access for a product. Generates a token if none exists."""
    product = await get_product_for_quick_access_management(product_id, current_user, db)

    # Check user is admin/owner of the product's organization
    if product.organization_id:
        role = await organization_ops.get_member_role(db, product.organization_id, current_user.id)
        if role not in (MemberRole.OWNER.value, MemberRole.ADMIN.value):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin or owner access required to manage quick access",
            )

    product = await product_ops.enable_quick_access(db, product, current_user.id)
    await db.commit()

    creator_name = await get_creator_name(db, product.quick_access_created_by)

    return QuickAccessStatus(
        enabled=product.quick_access_enabled,
        url=build_quick_access_url(product.quick_access_token)
        if product.quick_access_token
        else None,
        created_at=product.quick_access_created_at,
        created_by_name=creator_name,
    )


@router.post("/products/{product_id}/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_quick_access(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Disable quick access for a product. Token is preserved for re-enabling."""
    product = await get_product_for_quick_access_management(product_id, current_user, db)

    # Check user is admin/owner of the product's organization
    if product.organization_id:
        role = await organization_ops.get_member_role(db, product.organization_id, current_user.id)
        if role not in (MemberRole.OWNER.value, MemberRole.ADMIN.value):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin or owner access required to manage quick access",
            )

    await product_ops.disable_quick_access(db, product)
    await db.commit()


@router.post("/products/{product_id}/regenerate", response_model=QuickAccessStatus)
async def regenerate_quick_access_token(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuickAccessStatus:
    """Generate a new quick access token. Invalidates any existing links."""
    product = await get_product_for_quick_access_management(product_id, current_user, db)

    # Check user is admin/owner of the product's organization
    if product.organization_id:
        role = await organization_ops.get_member_role(db, product.organization_id, current_user.id)
        if role not in (MemberRole.OWNER.value, MemberRole.ADMIN.value):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin or owner access required to manage quick access",
            )

    product = await product_ops.regenerate_quick_access_token(db, product, current_user.id)
    await db.commit()

    creator_name = await get_creator_name(db, product.quick_access_created_by)

    return QuickAccessStatus(
        enabled=product.quick_access_enabled,
        url=build_quick_access_url(product.quick_access_token)
        if product.quick_access_token
        else None,
        created_at=product.quick_access_created_at,
        created_by_name=creator_name,
    )


# ---------------------------------------------------------------------------
# Access Endpoints (token-based, require org membership)
# ---------------------------------------------------------------------------


@router.get("/{token}", response_model=QuickAccessProductInfo)
async def get_product_by_token(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuickAccessProductInfo:
    """Get product info by quick access token. Requires org membership."""
    product = await product_ops.get_by_quick_access_token(db, token)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or disabled quick access link",
        )

    # Verify user is a member of the product's organization
    if product.organization_id:
        is_member = await organization_ops.is_member(db, product.organization_id, current_user.id)
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be a member of this organization to access this page",
            )

    # Get organization name
    org_name = "Personal Workspace"
    if product.organization_id:
        org = await organization_ops.get(db, product.organization_id)
        if org:
            org_name = org.name

    return QuickAccessProductInfo(
        product_id=product.id,
        product_name=product.name or "Unnamed Product",
        organization_name=org_name,
    )


@router.get("/{token}/entries", response_model=list[dict])  # type: ignore[type-arg]
async def get_entries_by_token(
    token: str,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, str | bool | None]]:
    """Get App Info entries for a product by quick access token. Requires org membership."""
    product = await product_ops.get_by_quick_access_token(db, token)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or disabled quick access link",
        )

    # Verify user is a member of the product's organization
    if product.organization_id:
        is_member = await organization_ops.is_member(db, product.organization_id, current_user.id)
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be a member of this organization to access this page",
            )

    # Get entries for the product (org-level access, not user-scoped)
    entries = await app_info_ops.get_by_product_for_org(
        db,
        product_id=product.id,
        skip=skip,
        limit=limit,
    )

    return [
        {
            "id": str(e.id),
            "key": e.key,
            "value": "********" if e.is_secret else e.value,
            "category": e.category,
            "is_secret": e.is_secret,
            "description": e.description,
            "target_file": e.target_file,
            "product_id": str(e.product_id) if e.product_id else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None,
        }
        for e in entries
    ]


@router.get("/{token}/entries/{entry_id}/reveal")
async def reveal_entry_by_token(
    token: str,
    entry_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | None]:
    """Reveal the actual value of a secret app info entry via quick access.

    **Authorization:** Requires editor or admin access to the product (not just org membership).
    **Rate limited:** 30 requests per minute per user.
    """
    product = await product_ops.get_by_quick_access_token(db, token)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or disabled quick access link",
        )

    # Verify user is a member of the product's organization
    if not product.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Product is not associated with an organization",
        )

    org_role = await organization_ops.get_member_role(
        db, product.organization_id, current_user.id
    )
    if not org_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member of this organization to access this page",
        )

    # Check for editor/admin access to reveal secrets
    # Org admins/owners always have admin access; others need explicit product access
    can_reveal = await product_access_ops.user_can_access_variables(
        db, product.id, current_user.id, org_role
    )
    if not can_reveal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You need editor or admin access to reveal secret values. "
            "Please contact your project Admin to request Editor access.",
        )

    # Rate limiting
    rate_limiter.check_rate_limit(current_user.id, "quick_access_reveal", REVEAL_LIMIT)

    # Get the specific entry
    entry = await app_info_ops.get_by_id_for_product(db, product_id=product.id, entry_id=entry_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App info entry not found",
        )

    # Decrypt the value before returning
    decrypted_value = app_info_ops.decrypt_entry_value(entry)
    return {"value": decrypted_value}
