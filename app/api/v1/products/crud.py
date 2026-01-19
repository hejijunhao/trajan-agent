"""Product CRUD operations: list, get, create, update, delete."""

import uuid as uuid_pkg

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SubscriptionContext,
    check_product_admin_access,
    check_product_editor_access,
    get_current_user,
    get_db_with_rls,
    get_subscription_context,
)
from app.domain import product_ops
from app.domain.organization_operations import organization_ops
from app.domain.product_access_operations import product_access_ops
from app.models.product import ProductCreate, ProductUpdate
from app.models.user import User

router = APIRouter()


@router.get("/", response_model=list[dict])
async def list_products(
    skip: int = 0,
    limit: int = 100,
    org_id: uuid_pkg.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """
    List all products the current user has access to.

    Args:
        org_id: Optional organization ID to filter by. If provided, only returns
                products from that organization. If not provided, returns products
                from all organizations the user is a member of.

    Returns products filtered by their access level:
    - Org owners/admins: see all products in their orgs
    - Org members/viewers: only see products they have explicit access to
    """
    # Get organizations to query - either specific org or all user's orgs
    if org_id:
        # Verify user is a member of this org
        org_role = await organization_ops.get_member_role(db, org_id, current_user.id)
        if not org_role:
            # User is not a member of this org, return empty list
            return []
        org = await organization_ops.get(db, org_id)
        if not org:
            return []
        user_orgs = [org]
    else:
        user_orgs = await organization_ops.get_for_user(db, current_user.id)

    accessible_products = []
    for org in user_orgs:
        # Get user's role in this org
        org_role = await organization_ops.get_member_role(db, org.id, current_user.id)
        if not org_role:
            continue

        # Get all products in this org
        org_products = await product_ops.get_by_organization(db, org.id)

        for product in org_products:
            # Check if user can access this product
            access = await product_access_ops.get_effective_access(
                db, product.id, current_user.id, org_role
            )
            if access != "none":
                accessible_products.append(product)

    # Apply pagination
    paginated = accessible_products[skip : skip + limit]

    # Build response with collaborator counts
    result = []
    for p in paginated:
        collab_count = await product_access_ops.get_product_collaborators_count(db, p.id)
        result.append(
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "icon": p.icon,
                "color": p.color,
                "analysis_status": p.analysis_status,
                "created_at": p.created_at.isoformat(),
                "updated_at": p.updated_at.isoformat(),
                "collaborator_count": collab_count,
            }
        )

    return result


@router.get("/{product_id}")
async def get_product(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Get a single product with all related entities.

    Access control: User must have at least viewer access to the product
    through their organization membership.
    """
    # Fetch product by ID (without user_id filter for org-based access)
    product = await product_ops.get_with_relations_by_id(db, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Check organization membership and product access
    if not product.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    org_role = await organization_ops.get_member_role(db, product.organization_id, current_user.id)
    if not org_role:
        # User is not a member of this product's organization
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Verify user has at least viewer access to this product
    access = await product_access_ops.get_effective_access(
        db, product_id, current_user.id, org_role
    )
    if access == "none":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "icon": product.icon,
        "color": product.color,
        "analysis_status": product.analysis_status,
        "analysis_error": product.analysis_error,
        "analysis_progress": product.analysis_progress,
        "product_overview": product.product_overview,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
        "repositories_count": len(product.repositories),
        "work_items_count": len(product.work_items),
        "documents_count": len(product.documents),
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    current_user: User = Depends(get_current_user),
    sub_ctx: SubscriptionContext = Depends(get_subscription_context),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Create a new product."""
    # Check for duplicate name
    existing = await product_ops.get_by_name(db, user_id=current_user.id, name=data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this name already exists",
        )

    # Include organization_id from subscription context
    product_data = data.model_dump()
    product_data["organization_id"] = sub_ctx.organization.id

    product = await product_ops.create(
        db,
        obj_in=product_data,
        user_id=current_user.id,
    )
    return {
        "id": str(product.id),
        "name": product.name,
        "description": product.description,
        "icon": product.icon,
        "color": product.color,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


@router.patch("/{product_id}")
async def update_product(
    product_id: uuid_pkg.UUID,
    data: ProductUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Update a product. Requires Editor or Admin access."""
    # Check product access first
    await check_product_editor_access(db, product_id, current_user.id)

    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    updated = await product_ops.update(
        db, db_obj=product, obj_in=data.model_dump(exclude_unset=True)
    )
    return {
        "id": str(updated.id),
        "name": updated.name,
        "description": updated.description,
        "icon": updated.icon,
        "color": updated.color,
        "created_at": updated.created_at.isoformat(),
        "updated_at": updated.updated_at.isoformat(),
    }


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Delete a product and all related entities. Requires Admin access."""
    # Check admin access first
    await check_product_admin_access(db, product_id, current_user.id)

    deleted = await product_ops.delete(db, id=product_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
