"""Product collaborator management: access control and team collaboration."""

import uuid as uuid_pkg

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import check_product_admin_access, get_current_user
from app.core.database import get_db
from app.domain import product_ops
from app.domain.organization_operations import organization_ops
from app.domain.product_access_operations import product_access_ops
from app.models.organization import MemberRole
from app.models.product_access import (
    ProductAccessCreate,
    ProductAccessLevel,
    ProductAccessWithUser,
    UserBasicInfo,
)
from app.models.user import User

router = APIRouter()


@router.get("/{product_id}/access")
async def get_my_product_access(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current user's access level for a product.

    Returns the effective access level considering both org role and explicit access.
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
        return {"access_level": "none"}
    org_role = await organization_ops.get_member_role(db, product.organization_id, current_user.id)
    if not org_role:
        return {"access_level": "none"}

    # Get effective access level
    access_level = await product_access_ops.get_effective_access(
        db, product_id, current_user.id, org_role
    )

    return {"access_level": access_level}


@router.get("/{product_id}/collaborators", response_model=list[ProductAccessWithUser])
async def list_collaborators(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all collaborators for a product with user details.

    Requires admin access to the product.
    Org owners/admins are NOT listed (they have automatic access).
    Only explicitly added collaborators are returned.
    """
    # Verify admin access
    await check_product_admin_access(db, product_id, current_user.id)

    # Get collaborators with user info
    collaborators = await product_access_ops.get_product_collaborators_with_users(db, product_id)

    # Format response with user details
    return [
        ProductAccessWithUser(
            id=collab.id,
            product_id=collab.product_id,
            user_id=collab.user_id,
            access_level=collab.access_level,
            created_at=collab.created_at,
            updated_at=collab.updated_at,
            user=UserBasicInfo(
                id=collab.user.id,
                email=collab.user.email,
                display_name=collab.user.display_name,
                avatar_url=collab.user.avatar_url,
            ),
        )
        for collab in collaborators
        if collab.user  # Safety check
    ]


@router.post("/{product_id}/collaborators", response_model=dict)
async def add_or_update_collaborator(
    product_id: uuid_pkg.UUID,
    data: ProductAccessCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a new collaborator or update existing access level.

    Requires admin access to the product.
    Cannot modify org owners/admins (they have automatic access).
    """
    # Verify admin access
    await check_product_admin_access(db, product_id, current_user.id)

    # Validate access level
    valid_levels = {level.value for level in ProductAccessLevel}
    if data.access_level not in valid_levels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid access level. Must be one of: {', '.join(valid_levels)}",
        )

    # Get product to check org
    product = await product_ops.get(db, product_id)
    if not product or not product.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Check if target user is org owner/admin (cannot modify their access)
    target_org_role = await organization_ops.get_member_role(
        db, product.organization_id, data.user_id
    )
    if target_org_role in (MemberRole.OWNER.value, MemberRole.ADMIN.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify access for organization owners or admins. "
            "They have automatic admin access to all projects.",
        )

    # Verify target user is org member
    if not target_org_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a member of this organization",
        )

    # Set access
    access = await product_access_ops.set_access(db, product_id, data.user_id, data.access_level)
    await db.commit()

    return {
        "id": str(access.id),
        "product_id": str(access.product_id),
        "user_id": str(access.user_id),
        "access_level": access.access_level,
        "message": "Access updated successfully",
    }


@router.delete("/{product_id}/collaborators/{user_id}")
async def remove_collaborator(
    product_id: uuid_pkg.UUID,
    user_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a collaborator's explicit access to a product.

    Requires admin access to the product.
    Cannot remove org owners/admins (they have automatic access).
    """
    # Verify admin access
    await check_product_admin_access(db, product_id, current_user.id)

    # Prevent self-removal
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own access",
        )

    # Remove access
    removed = await product_access_ops.remove_access(db, product_id, user_id)
    await db.commit()

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collaborator not found or already removed",
        )

    return {"status": "removed", "user_id": str(user_id)}
