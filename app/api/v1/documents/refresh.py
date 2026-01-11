"""Document refresh endpoints — AI-powered document updates."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.domain import document_ops, preferences_ops, product_ops, repository_ops
from app.models.user import User
from app.schemas.docs import (
    BulkRefreshResponse,
    RefreshDocumentDetailResponse,
    RefreshDocumentResponse,
)
from app.services.docs.document_refresher import DocumentRefresher
from app.services.github import GitHubService


async def refresh_document(
    document_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RefreshDocumentResponse:
    """
    Refresh a single document by comparing with current codebase.

    Reviews the document against the current state of the source files
    and updates if any information is outdated.
    """
    doc = await document_ops.get_by_user(db, user_id=current_user.id, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if not doc.product_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is not linked to a product",
        )

    # Get user's GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    if not preferences or not preferences.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token not configured. Please add your GitHub token in Settings.",
        )

    # Get linked repositories
    repos = await repository_ops.get_github_repos_by_product(
        db, user_id=current_user.id, product_id=doc.product_id
    )
    if not repos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No GitHub repositories linked to this product",
        )

    github_service = GitHubService(preferences.github_token)
    refresher = DocumentRefresher(db, github_service)

    result = await refresher.refresh_document(doc, repos)

    return RefreshDocumentResponse(
        document_id=result.document_id,
        status=result.status,
        changes_summary=result.changes_summary,
        error=result.error,
    )


async def refresh_all_documents(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkRefreshResponse:
    """
    Refresh all documents for a product.

    Scans all documents and compares them against the current state
    of the codebase. Updates any documents that have become outdated.
    """
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Get user's GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    if not preferences or not preferences.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token not configured. Please add your GitHub token in Settings.",
        )

    # Get linked repositories
    repos = await repository_ops.get_github_repos_by_product(
        db, user_id=current_user.id, product_id=product_id
    )
    if not repos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No GitHub repositories linked to this product",
        )

    github_service = GitHubService(preferences.github_token)
    refresher = DocumentRefresher(db, github_service)

    result = await refresher.refresh_all(
        product_id=str(product_id),
        user_id=str(current_user.id),
        repos=repos,
    )

    return BulkRefreshResponse(
        checked=result.checked,
        updated=result.updated,
        unchanged=result.unchanged,
        errors=result.errors,
        details=[
            RefreshDocumentDetailResponse(
                document_id=d.document_id,
                status=d.status,
                changes_summary=d.changes_summary,
                error=d.error,
            )
            for d in result.details
        ],
    )
