"""
GitHub integration endpoints for listing and importing repositories.
"""

import logging
import uuid as uuid_pkg
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SubscriptionContext,
    get_current_user,
    get_subscription_context_for_product,
    require_active_subscription,
)
from app.api.v1.products.analysis import maybe_auto_trigger_analysis
from app.api.v1.products.docs_generation import maybe_auto_trigger_docs
from app.core.database import get_db
from app.domain import product_ops, repository_ops
from app.domain.preferences_operations import preferences_ops
from app.domain.subscription_operations import subscription_ops
from app.models.user import User
from app.services.github import GitHubAPIError, GitHubService
from app.services.github.exceptions import GitHubRepoRenamed

router = APIRouter(prefix="/github", tags=["github"])
logger = logging.getLogger(__name__)


async def resolve_renamed_repo(
    github: GitHubService,
    rename_exc: GitHubRepoRenamed,
) -> object:
    """Resolve a renamed GitHub repo and fetch fresh details.

    Given a GitHubRepoRenamed exception (which may contain a new_full_name
    or a repo_id to resolve), determines the current name and fetches
    fresh repo details.

    Returns:
        The fresh RepoDetails object from GitHub.

    Raises:
        GitHubAPIError: If resolution or fetch fails.
        ValueError: If the new name cannot be determined.
    """
    new_full_name = rename_exc.new_full_name

    if not new_full_name and rename_exc.repo_id:
        resolved = await github.get_repo_by_id(rename_exc.repo_id)
        new_full_name = resolved.full_name

    if not new_full_name:
        raise ValueError("Repository was renamed but couldn't determine new name")

    new_owner, new_repo_name = new_full_name.split("/", 1)
    return await github.get_repo_details(new_owner, new_repo_name)


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
    docs_generation_triggered: bool = False
    analysis_triggered: bool = False


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
    """Get GitHub token for user, raising 400 if not configured.

    Automatically decrypts the token if encryption is enabled.
    """
    prefs = await preferences_ops.get_by_user_id(db, user_id)
    if not prefs or not prefs.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token not configured. Add your token in Settings > General.",
        )
    return preferences_ops.get_decrypted_token(prefs) or ""


# --- Endpoints ---


@router.get("/repos", response_model=GitHubReposListResponse)
async def list_github_repos(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(30, ge=1, le=100, description="Items per page"),
    sort: str = Query("updated", description="Sort by: updated, created, pushed, full_name"),
    visibility: str = Query("all", description="Visibility filter: all, public, private"),
    product_id: uuid_pkg.UUID | None = Query(
        None, description="Product ID to check import status against (product-specific check)"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GitHubReposListResponse:
    """
    List the authenticated user's GitHub repositories.

    Returns repos with their import status. When product_id is provided,
    marks repos as 'already_imported' only if they exist in THAT specific product.
    Without product_id, checks globally across all accessible products.
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

    # Check which repos are already imported
    # When product_id is provided, check only that specific product (fixes cross-project import bug)
    # When product_id is not provided, check globally across all accessible products
    repos_with_status: list[GitHubRepoPreview] = []
    for repo in result.repos:
        if product_id:
            # Product-specific check: only mark as imported if in THIS product
            existing = await repository_ops.get_by_github_id(db, product_id, repo.github_id)
        else:
            # Global check: mark as imported if in ANY accessible product
            existing = await repository_ops.find_by_github_id(db, repo.github_id)
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
    _sub: SubscriptionContext = Depends(require_active_subscription),
) -> ImportResponse:
    """
    Import selected GitHub repositories into a product.

    Fetches fresh metadata from GitHub and creates Repository records.
    Skips repos already imported to the same product.

    Repository limits are enforced based on the TARGET product's organization:
    - Free tier (Observer): Cannot exceed base limit
    - Paid tiers: Allowed to exceed with overage charges

    This ensures collaborators on paid organizations can import repos using
    that org's subscription limits, not their personal org's limits.
    """
    # Verify product exists and belongs to user
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=data.product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Get subscription context for the PRODUCT's organization (not user's default)
    # This fixes the cross-org subscription bug where free-tier collaborators
    # couldn't import repos to paid organizations
    sub_ctx = await get_subscription_context_for_product(db, data.product_id)

    # Check repo limit before import
    current_count = await repository_ops.count_by_org(db, sub_ctx.organization.id)

    # Pre-filter: count how many are actually new (not already in this product)
    new_repo_count = 0
    for github_id in data.github_ids:
        existing = await repository_ops.get_by_github_id(db, data.product_id, github_id)
        if not existing:
            new_repo_count += 1

    # Check if we can add all the new repos
    if new_repo_count > 0:
        limit_status = await subscription_ops.check_repo_limit(
            db,
            organization_id=sub_ctx.organization.id,
            current_repo_count=current_count,
            additional_count=new_repo_count,
        )

        if not limit_status.can_add:
            available = max(0, limit_status.base_limit - current_count)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot import {new_repo_count} repositories. "
                f"You have {current_count} repositories and a limit of {limit_status.base_limit}. "
                f"You can import {available} more. Upgrade your plan to add more.",
            )

    token = await get_github_token(db, current_user.id)
    github = GitHubService(token)

    imported: list[ImportedRepo] = []
    skipped: list[SkippedRepo] = []

    # Fetch user repos once upfront to avoid N+1 API calls
    user_repos = await github.get_user_repos(per_page=100, visibility="all")
    repos_by_id = {r.github_id: r for r in user_repos.repos}

    for github_id in data.github_ids:
        # Check if already imported to this specific product
        existing = await repository_ops.get_by_github_id(db, data.product_id, github_id)
        if existing:
            skipped.append(
                SkippedRepo(github_id=github_id, reason="Already imported to this product")
            )
            continue

        # Fetch fresh repo details from GitHub
        try:
            repo_data = repos_by_id.get(github_id)

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
                imported_by_user_id=current_user.id,
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

    # Commit the repo imports before attempting docs auto-trigger.
    # This ensures repos are saved even if the docs trigger fails (e.g., statement timeout
    # after long GitHub API calls holding the transaction open).
    if imported:
        await db.commit()

    # Auto-trigger docs generation if repos were actually imported
    docs_triggered = False
    if imported:
        try:
            docs_triggered = await maybe_auto_trigger_docs(
                product_id=data.product_id,
                user_id=current_user.id,
                db=db,
            )
        except Exception as e:
            # Log but don't fail the import - user can manually trigger docs
            logger.warning(
                f"Auto-trigger docs failed for product {data.product_id} after import: {e}. "
                "User can manually trigger docs generation."
            )

    # Auto-trigger project analysis if repos were actually imported
    analysis_triggered = False
    if imported:
        try:
            analysis_triggered = await maybe_auto_trigger_analysis(
                product_id=data.product_id,
                user_id=current_user.id,
                db=db,
            )
        except Exception as e:
            logger.warning(
                f"Auto-trigger analysis failed for product {data.product_id} after import: {e}. "
                "User can manually trigger analysis."
            )

    return ImportResponse(
        imported=imported,
        skipped=skipped,
        docs_generation_triggered=docs_triggered,
        analysis_triggered=analysis_triggered,
    )


@router.post("/refresh/{repository_id}")
async def refresh_repository_metadata(
    repository_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _sub: SubscriptionContext = Depends(require_active_subscription),
) -> dict[str, str | int | bool | None]:
    """
    Refresh a repository's metadata from GitHub.

    Updates stars, forks, description, and default branch.
    Only works for repositories with a github_id (imported from GitHub).
    Requires viewer access to the product (RLS enforced).
    """
    repo = await repository_ops.get(db, id=repository_id)
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
    except GitHubRepoRenamed as e:
        # Repository was renamed — resolve new name and fetch fresh data
        try:
            fresh_data = await resolve_renamed_repo(github, e)
        except (GitHubAPIError, ValueError) as resolve_err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Repository was renamed but resolution failed: {resolve_err}",
            ) from None

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

    # Update the repository with fresh data (including name if renamed)
    update_data = {
        "name": fresh_data.name,
        "full_name": fresh_data.full_name,
        "url": fresh_data.url,
        "description": fresh_data.description,
        "default_branch": fresh_data.default_branch,
        "stars_count": fresh_data.stars_count,
        "forks_count": fresh_data.forks_count,
        "language": fresh_data.language,
        "is_private": fresh_data.is_private,
    }
    updated = await repository_ops.update(db, db_obj=repo, obj_in=update_data)

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
    _sub: SubscriptionContext = Depends(require_active_subscription),
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

    # Get all GitHub-linked repos for this product (RLS enforces access)
    repos = await repository_ops.get_github_repos_by_product(db, product_id=data.product_id)

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
        except GitHubRepoRenamed as e:
            # Repository was renamed — resolve new name and fetch fresh data
            try:
                fresh_data = await resolve_renamed_repo(github, e)
            except (GitHubAPIError, ValueError) as resolve_err:
                failed.append(
                    FailedRefresh(
                        repository_id=str(repo.id),
                        name=repo.name or "Unknown",
                        reason=f"Renamed but resolution failed: {resolve_err}",
                    )
                )
                continue
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
            continue

        # Update repository with fresh data (including name/full_name if renamed)
        await repository_ops.update(
            db,
            db_obj=repo,
            obj_in={
                "name": fresh_data.name,
                "full_name": fresh_data.full_name,
                "url": fresh_data.url,
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
                name=fresh_data.name,
            )
        )

    return BulkRefreshResponse(refreshed=refreshed, failed=failed)
