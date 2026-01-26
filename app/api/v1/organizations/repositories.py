"""Organization-wide repository listing for downgrade flows.

This endpoint returns all repositories across all products in an organization,
grouped by product for easy display in the repo selection modal.
"""

import uuid as uuid_pkg
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.api.v1.organizations.helpers import require_org_access
from app.api.v1.organizations.schemas import OrgRepositoriesListResponse, OrgRepositoryResponse
from app.domain import repository_ops


async def list_org_repositories(
    org_id: uuid_pkg.UUID,
    db: Annotated[AsyncSession, Depends(DbSession)],
    user: Annotated[CurrentUser, Depends()],
) -> OrgRepositoriesListResponse:
    """
    List all repositories across all products in an organization.

    Returns repositories with their product names for grouping in UI.
    Useful for subscription downgrade flows where users must select
    which repos to keep.

    Requires: Organization membership (any role).
    """
    # Verify user has access to the organization
    await require_org_access(db, org_id, user)

    # Get all repositories for the organization
    repos = await repository_ops.get_by_org_with_products(db, org_id)
    total_count = await repository_ops.count_by_org(db, org_id)

    # Transform to response format
    repo_responses = [
        OrgRepositoryResponse(
            id=str(repo.id),
            name=repo.name or "",
            full_name=repo.full_name,
            description=repo.description,
            default_branch=repo.default_branch,
            product_id=str(repo.product_id),
            product_name=repo.product.name if repo.product else "Unknown",
            updated_at=repo.updated_at.isoformat() if repo.updated_at else None,
        )
        for repo in repos
    ]

    return OrgRepositoriesListResponse(
        repositories=repo_responses,
        total_count=total_count,
    )
