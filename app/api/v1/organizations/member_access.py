"""Member product access endpoints - bulk view/manage product access for org members."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.api.v1.organizations.helpers import require_org_access
from app.domain import org_member_ops, organization_ops, product_ops
from app.domain.product_access_operations import product_access_ops
from app.models.organization import MemberRole
from app.models.user import User


class MemberProductAccessItem(BaseModel):
    """Single product with its access level for a member."""

    product_id: str
    product_name: str
    product_color: str | None
    access_level: str | None  # None = no explicit access


class MemberProductAccessResponse(BaseModel):
    """Response containing all products and member's access to each."""

    member_id: str
    user_id: str
    org_role: str
    has_automatic_access: bool  # True for owner/admin
    products: list[MemberProductAccessItem]


async def get_member_product_access(
    org_id: uuid_pkg.UUID,
    member_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> MemberProductAccessResponse:
    """
    Get all products in an organization with the specified member's access level for each.

    Requires admin or owner role in the organization.
    """
    # Verify org exists
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    # Require admin or owner
    await require_org_access(db, org_id, user, min_role=MemberRole.ADMIN)

    # Get the target member
    member = await org_member_ops.get(db, member_id)
    if not member or member.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    # Determine if member has automatic admin access (owner/admin role)
    has_automatic_access = member.role in (MemberRole.OWNER.value, MemberRole.ADMIN.value)

    # Get all products in the organization
    org_products = await product_ops.get_by_organization(db, org_id)

    # Get member's explicit access for all products
    access_map = await product_access_ops.get_user_access_for_org_products(
        db, org_id, member.user_id
    )

    # Build response with all products and their access levels
    products = [
        MemberProductAccessItem(
            product_id=str(product.id),
            product_name=product.name or "Unnamed Project",
            product_color=product.color,
            access_level=access_map.get(product.id),
        )
        for product in org_products
    ]

    return MemberProductAccessResponse(
        member_id=str(member.id),
        user_id=str(member.user_id),
        org_role=member.role,
        has_automatic_access=has_automatic_access,
        products=products,
    )
