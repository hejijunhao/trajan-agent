"""
GitHub integration endpoints for listing and importing repositories.
"""

import uuid as uuid_pkg
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.domain import product_ops, repository_ops
from app.domain.preferences_operations import preferences_ops
from app.models.user import User
from app.services.github import GitHubAPIError, GitHubService

router = APIRouter(prefix="/github", tags=["github"])


# --- Response Models ---


class GitHubRepoPreview(BaseModel):
    """Preview of a GitHub repository for import selection."""

    github_id: int
    name: str
    full_name: str
    description: str | None
    url: str
    default_branch: str
    is_private: bool
    language: str | None
    stars_count: int
    forks_count: int
    updated_at: str
    already_imported: bool
    imported_to_product_id: str | None


class GitHubReposListResponse(BaseModel):
    """Response for listing GitHub repos."""

    repos: list[GitHubRepoPreview]
    page: int
    per_page: int
    has_more: bool
    rate_limit_remaining: int | None


class ImportRequest(BaseModel):
    """Request to import GitHub repos into a product."""

    product_id: uuid_pkg.UUID
    github_ids: list[int]


class ImportedRepo(BaseModel):
    """Successfully imported repository."""

    github_id: int
    repository_id: str
    name: str


class SkippedRepo(BaseModel):
    """Repository that was skipped during import."""

    github_id: int
    reason: str


class ImportResponse(BaseModel):
    """Response from import operation."""

    imported: list[ImportedRepo]
    skipped: list[SkippedRepo]


class BulkRefreshRequest(BaseModel):
    """Request to refresh multiple GitHub repos."""

    product_id: uuid_pkg.UUID


class RefreshedRepo(BaseModel):
    """Successfully refreshed repository."""

    repository_id: str
    name: str


class FailedRefresh(BaseModel):
    """Repository that failed to refresh."""

    repository_id: str
    name: str
    reason: str


class BulkRefreshResponse(BaseModel):
    """Response from bulk refresh operation."""

    refreshed: list[RefreshedRepo]
    failed: list[FailedRefresh]


# --- Helper Functions ---


async def get_github_token(db: AsyncSession, user_id: uuid_pkg.UUID) -> str:
    """Get GitHub token for user, raising 400 if not configured."""
    prefs = await preferences_ops.get_by_user_id(db, user_id)
    if not prefs or not prefs.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token not configured. Add your token in Settings > General.",
        )
    return prefs.github_token


# --- Endpoints ---


@router.get("/repos", response_model=GitHubReposListResponse)
async def list_github_repos(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(30, ge=1, le=100, description="Items per page"),
    sort: str = Query("updated", description="Sort by: updated, created, pushed, full_name"),
    visibility: str = Query("all", description="Visibility filter: all, public, private"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GitHubReposListResponse:
    """
    List the authenticated user's GitHub repositories.

    Returns repos with their import status for this user.
    Requires a GitHub token to be configured in user preferences.
    """
    token = await get_github_token(db, current_user.id)
    github = GitHubService(token)

    try:
        result = await github.get_user_repos(
            page=page,
            per_page=per_page,
            sort=sort,
            visibility=visibility,
        )
    except GitHubAPIError as e:
        detail = e.message
        if e.rate_limit_reset:
            import time

            reset_in = max(0, e.rate_limit_reset - int(time.time()))
            minutes = reset_in // 60
            detail = f"{e.message}. Rate limit resets in {minutes} minutes."
        raise HTTPException(
            status_code=e.status_code or status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from None

    # Check which repos are already imported for this user
    repos_with_status: list[GitHubRepoPreview] = []
    for repo in result.repos:
        existing = await repository_ops.get_by_github_id(db, current_user.id, repo.github_id)
        repos_with_status.append(
            GitHubRepoPreview(
                **asdict(repo),
                already_imported=existing is not None,
                imported_to_product_id=str(existing.product_id) if existing else None,
            )
        )

    return GitHubReposListResponse(
        repos=repos_with_status,
        page=page,
        per_page=per_page,
        has_more=result.has_more,
        rate_limit_remaining=result.rate_limit_remaining,
    )


@router.post("/import", response_model=ImportResponse)
async def import_github_repos(
    data: ImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImportResponse:
    """
    Import selected GitHub repositories into a product.

    Fetches fresh metadata from GitHub and creates Repository records.
    Skips repos already imported to the same product.
    """
    # Verify product exists and belongs to user
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=data.product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    token = await get_github_token(db, current_user.id)
    github = GitHubService(token)

    imported: list[ImportedRepo] = []
    skipped: list[SkippedRepo] = []

    for github_id in data.github_ids:
        # Check if already imported to this product
        existing = await repository_ops.get_by_github_id(db, current_user.id, github_id)
        if existing and existing.product_id == data.product_id:
            skipped.append(
                SkippedRepo(github_id=github_id, reason="Already imported to this product")
            )
            continue

        if existing:
            # Imported to different product - skip with explanation
            skipped.append(
                SkippedRepo(
                    github_id=github_id,
                    reason=f"Already imported to product {existing.product_id}",
                )
            )
            continue

        # Fetch fresh repo details from GitHub
        try:
            # We need owner/repo from the github_id, so we'll search in the user's repos
            # For efficiency, we could cache the list, but for now re-fetch per repo
            user_repos = await github.get_user_repos(per_page=100, visibility="all")
            repo_data = next((r for r in user_repos.repos if r.github_id == github_id), None)

            if not repo_data:
                # Try fetching with more pages if not found
                skipped.append(
                    SkippedRepo(github_id=github_id, reason="Repository not found in GitHub")
                )
                continue

            # Fetch full details using owner/repo
            owner, repo_name = repo_data.full_name.split("/", 1)
            fresh_data = await github.get_repo_details(owner, repo_name)

            # Create repository record
            repo = await repository_ops.create(
                db,
                obj_in={
                    "product_id": data.product_id,
                    "name": fresh_data.name,
                    "full_name": fresh_data.full_name,
                    "description": fresh_data.description,
                    "url": fresh_data.url,
                    "default_branch": fresh_data.default_branch,
                    "is_private": fresh_data.is_private,
                    "language": fresh_data.language,
                    "github_id": fresh_data.github_id,
                    "stars_count": fresh_data.stars_count,
                    "forks_count": fresh_data.forks_count,
                },
                user_id=current_user.id,
            )

            imported.append(
                ImportedRepo(
                    github_id=fresh_data.github_id,
                    repository_id=str(repo.id),
                    name=fresh_data.name,
                )
            )

        except GitHubAPIError as e:
            skipped.append(SkippedRepo(github_id=github_id, reason=e.message))
            continue

    return ImportResponse(imported=imported, skipped=skipped)


@router.post("/refresh/{repository_id}")
async def refresh_repository_metadata(
    repository_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | int | bool | None]:
    """
    Refresh a repository's metadata from GitHub.

    Updates stars, forks, description, and default branch.
    Only works for repositories with a github_id (imported from GitHub).
    """
    repo = await repository_ops.get_by_user(db, user_id=current_user.id, id=repository_id)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    if not repo.github_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a GitHub repository",
        )

    if not repo.full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository missing full_name for GitHub lookup",
        )

    token = await get_github_token(db, current_user.id)
    github = GitHubService(token)

    try:
        owner, repo_name = repo.full_name.split("/", 1)
        fresh_data = await github.get_repo_details(owner, repo_name)
    except GitHubAPIError as e:
        if e.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository no longer exists on GitHub",
            ) from None
        detail = e.message
        if e.rate_limit_reset:
            import time

            reset_in = max(0, e.rate_limit_reset - int(time.time()))
            minutes = reset_in // 60
            detail = f"{e.message}. Rate limit resets in {minutes} minutes."
        raise HTTPException(
            status_code=e.status_code or status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from None

    # Update the repository with fresh data
    updated = await repository_ops.update(
        db,
        db_obj=repo,
        obj_in={
            "description": fresh_data.description,
            "default_branch": fresh_data.default_branch,
            "stars_count": fresh_data.stars_count,
            "forks_count": fresh_data.forks_count,
            "language": fresh_data.language,
            "is_private": fresh_data.is_private,
        },
    )

    return {
        "id": str(updated.id),
        "name": updated.name,
        "full_name": updated.full_name,
        "description": updated.description,
        "url": updated.url,
        "default_branch": updated.default_branch,
        "is_private": updated.is_private,
        "language": updated.language,
        "github_id": updated.github_id,
        "stars_count": updated.stars_count,
        "forks_count": updated.forks_count,
        "product_id": str(updated.product_id) if updated.product_id else None,
        "created_at": updated.created_at.isoformat(),
        "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
    }


@router.post("/refresh-all", response_model=BulkRefreshResponse)
async def bulk_refresh_github_repos(
    data: BulkRefreshRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkRefreshResponse:
    """
    Refresh metadata for all GitHub-linked repositories in a product.

    Updates stars, forks, description, and default branch for each repo.
    Continues processing even if some repos fail.
    """
    # Verify product exists and belongs to user
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=data.product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    token = await get_github_token(db, current_user.id)
    github = GitHubService(token)

    # Get all GitHub-linked repos for this product
    repos = await repository_ops.get_github_repos_by_product(
        db, user_id=current_user.id, product_id=data.product_id
    )

    if not repos:
        return BulkRefreshResponse(refreshed=[], failed=[])

    refreshed: list[RefreshedRepo] = []
    failed: list[FailedRefresh] = []

    for repo in repos:
        if not repo.full_name:
            failed.append(
                FailedRefresh(
                    repository_id=str(repo.id),
                    name=repo.name or "Unknown",
                    reason="Missing full_name for GitHub lookup",
                )
            )
            continue

        try:
            owner, repo_name = repo.full_name.split("/", 1)
            fresh_data = await github.get_repo_details(owner, repo_name)

            await repository_ops.update(
                db,
                db_obj=repo,
                obj_in={
                    "description": fresh_data.description,
                    "default_branch": fresh_data.default_branch,
                    "stars_count": fresh_data.stars_count,
                    "forks_count": fresh_data.forks_count,
                    "language": fresh_data.language,
                    "is_private": fresh_data.is_private,
                },
            )

            refreshed.append(
                RefreshedRepo(
                    repository_id=str(repo.id),
                    name=repo.name or fresh_data.name,
                )
            )
        except GitHubAPIError as e:
            reason = e.message
            if e.status_code == 404:
                reason = "Repository no longer exists on GitHub"
            elif e.rate_limit_reset:
                import time

                reset_in = max(0, e.rate_limit_reset - int(time.time()))
                minutes = reset_in // 60
                reason = f"{e.message}. Rate limit resets in {minutes} minutes."
            failed.append(
                FailedRefresh(
                    repository_id=str(repo.id),
                    name=repo.name or "Unknown",
                    reason=reason,
                )
            )

    return BulkRefreshResponse(refreshed=refreshed, failed=failed)
