"""Organization CRUD endpoints."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.api.v1.organizations.helpers import require_org_access
from app.api.v1.organizations.schemas import (
    OrganizationDetailResponse,
    OrganizationResponse,
    PlanResponse,
)
from app.config.plans import PLANS
from app.domain import org_member_ops, organization_ops
from app.models.organization import MemberRole, OrganizationCreate, OrganizationUpdate
from app.models.user import User


async def list_organizations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> list[OrganizationResponse]:
    """
    List all organizations the user is a member of.

    Returns organizations ordered by creation date (newest first).
    """
    orgs = await organization_ops.get_for_user(db, user.id)

    result = []
    for org in orgs:
        role = await organization_ops.get_member_role(db, org.id, user.id)
        result.append(
            OrganizationResponse(
                id=str(org.id),
                name=org.name,
                slug=org.slug,
                owner_id=str(org.owner_id),
                created_at=org.created_at.isoformat(),
                updated_at=org.updated_at.isoformat() if org.updated_at else None,
                is_personal=org.owner_id == user.id,
                role=role or MemberRole.MEMBER.value,
            )
        )

    return result


async def create_organization(
    data: OrganizationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> OrganizationResponse:
    """
    Create a new organization.

    The creating user becomes the owner.
    """
    org = await organization_ops.create(
        db,
        name=data.name,
        owner_id=user.id,
        slug=data.slug,
    )
    await db.commit()

    return OrganizationResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        owner_id=str(org.owner_id),
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat() if org.updated_at else None,
        is_personal=True,
        role=MemberRole.OWNER.value,
    )


async def list_plans(
    _user: User = Depends(get_current_user),
) -> list[PlanResponse]:
    """
    List all available plan tiers.

    Returns configuration details for all plans (for pricing display).
    """
    return [
        PlanResponse(
            tier=plan.tier,
            display_name=plan.display_name,
            price_monthly=plan.price_monthly,
            base_repo_limit=plan.base_repo_limit,
            overage_repo_price=plan.overage_repo_price,
            allows_overages=plan.allows_overages,
            features=plan.to_features_dict(),
            analysis_frequency=plan.analysis_frequency,
        )
        for plan in PLANS.values()
    ]


async def get_organization(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> OrganizationDetailResponse:
    """
    Get detailed information about an organization.

    Requires membership in the organization.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    role = await require_org_access(db, org_id, user)
    member_count = await org_member_ops.count_by_org(db, org_id)

    return OrganizationDetailResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        owner_id=str(org.owner_id),
        settings=org.settings,
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat() if org.updated_at else None,
        role=role,
        member_count=member_count,
    )


async def update_organization(
    org_id: uuid_pkg.UUID,
    data: OrganizationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> OrganizationDetailResponse:
    """
    Update an organization.

    Requires admin or owner role.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    role = await require_org_access(db, org_id, user, min_role=MemberRole.ADMIN)

    # Update organization
    updates = data.model_dump(exclude_unset=True)
    if updates:
        org = await organization_ops.update(db, org, updates)

    await db.commit()

    member_count = await org_member_ops.count_by_org(db, org_id)

    return OrganizationDetailResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        owner_id=str(org.owner_id),
        settings=org.settings,
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat() if org.updated_at else None,
        role=role,
        member_count=member_count,
    )


async def delete_organization(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> None:
    """
    Delete an organization.

    Requires owner role. This will delete all organization data including
    products, repositories, and subscriptions.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await require_org_access(db, org_id, user, min_role=MemberRole.OWNER)

    await organization_ops.delete(db, org_id)
    await db.commit()
