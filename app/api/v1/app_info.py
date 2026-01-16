import uuid as uuid_pkg

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.core.database import get_db
from app.domain import app_info_ops
from app.domain.organization_operations import organization_ops
from app.domain.product_access_operations import product_access_ops
from app.domain.product_operations import product_ops
from app.models.app_info import (
    AppInfoBulkCreate,
    AppInfoBulkResponse,
    AppInfoCreate,
    AppInfoExportEntry,
    AppInfoExportResponse,
    AppInfoUpdate,
)
from app.models.user import User

router = APIRouter(prefix="/app-info", tags=["app info"])


async def _check_variables_access(
    db: AsyncSession,
    product_id: uuid_pkg.UUID,
    user_id: uuid_pkg.UUID,
) -> None:
    """
    Check if user has access to environment variables for a product.

    Raises 404 if product not found.
    Raises 403 if user doesn't have editor/admin access.
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
    org_role = await organization_ops.get_member_role(db, product.organization_id, user_id)
    if not org_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    # Check if user can access variables (editor or admin only)
    can_access = await product_access_ops.user_can_access_variables(
        db, product_id, user_id, org_role
    )
    if not can_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to environment variables. "
            "Please contact your project Admin to request Editor access.",
        )


@router.get("", response_model=list[dict])
async def list_app_info(
    product_id: uuid_pkg.UUID = Query(..., description="Filter by product"),
    category: str | None = Query(None, description="Filter by category"),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """List app info entries for a product."""
    # Check variables access
    await _check_variables_access(db, product_id, current_user.id)

    entries = await app_info_ops.get_by_product(
        db,
        user_id=current_user.id,
        product_id=product_id,
        category=category,
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
            "created_at": e.created_at.isoformat(),
            "updated_at": e.updated_at.isoformat(),
        }
        for e in entries
    ]


@router.get("/export", response_model=AppInfoExportResponse)
async def export_app_info(
    product_id: uuid_pkg.UUID = Query(..., description="Product to export from"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """
    Export all app info entries with revealed secret values.

    Returns all entries for a product with their actual values (secrets unmasked),
    ready for formatting as a .env file.
    """
    # Check variables access
    await _check_variables_access(db, product_id, current_user.id)

    entries = await app_info_ops.get_by_product(
        db,
        user_id=current_user.id,
        product_id=product_id,
        limit=1000,  # Reasonable limit for export
    )

    return AppInfoExportResponse(
        entries=[
            AppInfoExportEntry(
                key=e.key or "",
                value=e.value or "",
                category=e.category,
                is_secret=e.is_secret or False,
                description=e.description,
                target_file=e.target_file,
            )
            for e in entries
        ]
    )


@router.get("/{app_info_id}")
async def get_app_info(
    app_info_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Get a single app info entry."""
    entry = await app_info_ops.get_by_user(db, user_id=current_user.id, id=app_info_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App info not found",
        )

    # Check variables access
    if entry.product_id:
        await _check_variables_access(db, entry.product_id, current_user.id)

    return {
        "id": str(entry.id),
        "key": entry.key,
        "value": "********" if entry.is_secret else entry.value,
        "category": entry.category,
        "is_secret": entry.is_secret,
        "description": entry.description,
        "target_file": entry.target_file,
        "product_id": str(entry.product_id) if entry.product_id else None,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_app_info(
    data: AppInfoCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Create a new app info entry."""
    # Check variables access
    await _check_variables_access(db, data.product_id, current_user.id)

    # Check for duplicate key in product
    existing = await app_info_ops.get_by_key(
        db, user_id=current_user.id, product_id=data.product_id, key=data.key
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="App info with this key already exists for this product",
        )

    entry = await app_info_ops.create(
        db,
        obj_in=data.model_dump(),
        user_id=current_user.id,
    )
    return {
        "id": str(entry.id),
        "key": entry.key,
        "value": "********" if entry.is_secret else entry.value,
        "category": entry.category,
        "is_secret": entry.is_secret,
        "description": entry.description,
        "target_file": entry.target_file,
        "product_id": str(entry.product_id) if entry.product_id else None,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


@router.patch("/{app_info_id}")
async def update_app_info(
    app_info_id: uuid_pkg.UUID,
    data: AppInfoUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Update an app info entry."""
    entry = await app_info_ops.get_by_user(db, user_id=current_user.id, id=app_info_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App info not found",
        )

    # Check variables access
    if entry.product_id:
        await _check_variables_access(db, entry.product_id, current_user.id)

    updated = await app_info_ops.update(
        db, db_obj=entry, obj_in=data.model_dump(exclude_unset=True)
    )
    return {
        "id": str(updated.id),
        "key": updated.key,
        "value": "********" if updated.is_secret else updated.value,
        "category": updated.category,
        "is_secret": updated.is_secret,
        "description": updated.description,
        "target_file": updated.target_file,
        "product_id": str(updated.product_id) if updated.product_id else None,
        "created_at": updated.created_at.isoformat(),
        "updated_at": updated.updated_at.isoformat(),
    }


@router.delete("/{app_info_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_info(
    app_info_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Delete an app info entry."""
    # First get the entry to check access
    entry = await app_info_ops.get_by_user(db, user_id=current_user.id, id=app_info_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App info not found",
        )

    # Check variables access
    if entry.product_id:
        await _check_variables_access(db, entry.product_id, current_user.id)

    await app_info_ops.delete(db, id=app_info_id, user_id=current_user.id)


@router.get("/{app_info_id}/reveal")
async def reveal_app_info_value(
    app_info_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Reveal the actual value of a secret app info entry for copying."""
    entry = await app_info_ops.get_by_user(db, user_id=current_user.id, id=app_info_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App info not found",
        )

    # Check variables access
    if entry.product_id:
        await _check_variables_access(db, entry.product_id, current_user.id)

    return {"value": entry.value}


@router.post("/bulk", response_model=AppInfoBulkResponse, status_code=status.HTTP_201_CREATED)
async def bulk_create_app_info(
    data: AppInfoBulkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """
    Bulk create app info entries from parsed .env content.

    Entries with duplicate keys (already existing in the product) are skipped.
    Duplicate keys within the request take the last occurrence.
    """
    # Check variables access
    await _check_variables_access(db, data.product_id, current_user.id)

    created, skipped = await app_info_ops.bulk_create(
        db,
        user_id=current_user.id,
        product_id=data.product_id,
        entries=data.entries,
    )

    return AppInfoBulkResponse(
        created=[
            {
                "id": str(e.id),
                "key": e.key,
                "value": "********" if e.is_secret else e.value,
                "category": e.category,
                "is_secret": e.is_secret,
                "description": e.description,
                "target_file": e.target_file,
                "product_id": str(e.product_id) if e.product_id else None,
                "created_at": e.created_at.isoformat(),
                "updated_at": e.updated_at.isoformat(),
            }
            for e in created
        ],
        skipped=skipped,
    )
