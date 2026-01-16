import uuid as uuid_pkg

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SubscriptionContext,
    check_product_editor_access,
    get_current_user,
    get_subscription_context,
)
from app.core.database import get_db
from app.domain import repository_ops
from app.domain.subscription_operations import subscription_ops
from app.models.repository import RepositoryCreate, RepositoryUpdate
from app.models.user import User

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.get("", response_model=list[dict])
async def list_repositories(
    product_id: uuid_pkg.UUID | None = Query(None, description="Filter by product"),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List repositories, optionally filtered by product."""
    repos = await repository_ops.get_by_product(
        db,
        user_id=current_user.id,
        product_id=product_id,
        skip=skip,
        limit=limit,
    )
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "full_name": r.full_name,
            "description": r.description,
            "url": r.url,
            "default_branch": r.default_branch,
            "is_private": r.is_private,
            "language": r.language,
            "github_id": r.github_id,
            "stars_count": r.stars_count,
            "forks_count": r.forks_count,
            "product_id": str(r.product_id) if r.product_id else None,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in repos
    ]


@router.get("/{repository_id}")
async def get_repository(
    repository_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single repository."""
    repo = await repository_ops.get_by_user(db, user_id=current_user.id, id=repository_id)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    return {
        "id": str(repo.id),
        "name": repo.name,
        "full_name": repo.full_name,
        "description": repo.description,
        "url": repo.url,
        "default_branch": repo.default_branch,
        "is_private": repo.is_private,
        "language": repo.language,
        "github_id": repo.github_id,
        "stars_count": repo.stars_count,
        "forks_count": repo.forks_count,
        "product_id": str(repo.product_id) if repo.product_id else None,
        "created_at": repo.created_at.isoformat(),
        "updated_at": repo.updated_at.isoformat(),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_repository(
    data: RepositoryCreate,
    current_user: User = Depends(get_current_user),
    sub_ctx: SubscriptionContext = Depends(get_subscription_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new repository.

    Repository limits are enforced based on subscription plan:
    - Free tier (Observer): Cannot exceed base limit
    - Paid tiers: Allowed to exceed with overage charges

    Requires Editor or Admin access to the product.
    """
    # Check product access
    if data.product_id:
        await check_product_editor_access(db, data.product_id, current_user.id)

    # Check repo limit before creation
    current_count = await repository_ops.count_by_org(db, sub_ctx.organization.id)
    limit_status = await subscription_ops.check_repo_limit(
        db,
        organization_id=sub_ctx.organization.id,
        current_repo_count=current_count,
        additional_count=1,
    )

    if not limit_status.can_add:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Repository limit reached ({limit_status.base_limit}). "
            f"Upgrade your plan to add more repositories.",
        )

    # Warn about overage for paid plans (but still allow)
    # This is informational - actual billing happens via Stripe metered usage

    obj_data = data.model_dump()
    if obj_data.get("full_name") is None:
        obj_data["full_name"] = obj_data["name"]
    repo = await repository_ops.create(
        db,
        obj_in=obj_data,
        user_id=current_user.id,
    )
    return {
        "id": str(repo.id),
        "name": repo.name,
        "full_name": repo.full_name,
        "description": repo.description,
        "url": repo.url,
        "product_id": str(repo.product_id) if repo.product_id else None,
        "created_at": repo.created_at.isoformat(),
        "updated_at": repo.updated_at.isoformat(),
    }


@router.patch("/{repository_id}")
async def update_repository(
    repository_id: uuid_pkg.UUID,
    data: RepositoryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a repository. Requires Editor or Admin access to the product."""
    repo = await repository_ops.get_by_user(db, user_id=current_user.id, id=repository_id)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    # Check product access
    if repo.product_id:
        await check_product_editor_access(db, repo.product_id, current_user.id)

    updated = await repository_ops.update(
        db, db_obj=repo, obj_in=data.model_dump(exclude_unset=True)
    )
    return {
        "id": str(updated.id),
        "name": updated.name,
        "full_name": updated.full_name,
        "description": updated.description,
        "url": updated.url,
        "product_id": str(updated.product_id) if updated.product_id else None,
        "created_at": updated.created_at.isoformat(),
        "updated_at": updated.updated_at.isoformat(),
    }


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(
    repository_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a repository. Requires Editor or Admin access to the product."""
    # Get repo first to check product access
    repo = await repository_ops.get_by_user(db, user_id=current_user.id, id=repository_id)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    # Check product access
    if repo.product_id:
        await check_product_editor_access(db, repo.product_id, current_user.id)

    await repository_ops.delete(db, id=repository_id, user_id=current_user.id)
