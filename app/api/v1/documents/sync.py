"""GitHub synchronization endpoints for documents."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.documents.crud import serialize_document
from app.core.database import get_db
from app.domain import document_ops, preferences_ops, product_ops, repository_ops
from app.models.user import User
from app.schemas.docs import (
    DocsSyncStatusResponse,
    DocumentSyncStatusResponse,
    ImportDocsResponse,
    SyncDocsRequest,
    SyncDocsResponse,
)
from app.services.docs.sync_service import DocsSyncService
from app.services.github import GitHubService


async def import_docs_from_repo(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImportDocsResponse:
    """
    Import documentation from linked GitHub repositories.

    Scans all repositories linked to the product for docs/ folder
    and imports markdown files with sync tracking.
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
    sync_service = DocsSyncService(db, github_service)

    total_imported = 0
    total_updated = 0
    total_skipped = 0

    for repo in repos:
        if repo.full_name:
            result = await sync_service.import_from_repo(repo)
            total_imported += result.imported
            total_updated += result.updated
            total_skipped += result.skipped

    return ImportDocsResponse(
        imported=total_imported,
        updated=total_updated,
        skipped=total_skipped,
    )


async def get_docs_sync_status(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocsSyncStatusResponse:
    """
    Check sync status for all documents in a product.

    Returns which documents have local changes, remote changes,
    or are in sync with GitHub.
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
        # Return empty status if no token
        return DocsSyncStatusResponse(
            documents=[],
            has_local_changes=False,
            has_remote_changes=False,
        )

    github_service = GitHubService(preferences.github_token)
    sync_service = DocsSyncService(db, github_service)

    statuses = await sync_service.check_for_updates(
        product_id=str(product_id),
        user_id=str(current_user.id),
    )

    return DocsSyncStatusResponse(
        documents=[
            DocumentSyncStatusResponse(
                document_id=s.document_id,
                status=s.status,
                local_sha=s.local_sha,
                remote_sha=s.remote_sha,
                error=s.error,
            )
            for s in statuses
        ],
        has_local_changes=any(s.status == "local_changes" for s in statuses),
        has_remote_changes=any(s.status == "remote_changes" for s in statuses),
    )


async def pull_remote_changes(
    document_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull latest content from GitHub for a document.

    Overwrites local content with remote version.
    """
    doc = await document_ops.get_by_user(db, user_id=current_user.id, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if not doc.github_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is not synced with GitHub",
        )

    # Get user's GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    if not preferences or not preferences.github_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token not configured",
        )

    github_service = GitHubService(preferences.github_token)
    sync_service = DocsSyncService(db, github_service)

    updated_doc = await sync_service.pull_remote_changes(
        document_id=str(document_id),
        user_id=str(current_user.id),
    )

    if not updated_doc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to pull remote changes",
        )

    return serialize_document(updated_doc)


async def sync_docs_to_repo(
    product_id: uuid_pkg.UUID,
    data: SyncDocsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SyncDocsResponse:
    """
    Push documentation to linked GitHub repository.

    Syncs specified documents (or all with local changes) to the
    repository's docs/ folder.
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

    # Get documents to sync
    if data.document_ids:
        documents = []
        for doc_id in data.document_ids:
            doc = await document_ops.get_by_user(
                db, user_id=current_user.id, id=uuid_pkg.UUID(doc_id)
            )
            if doc:
                documents.append(doc)
    else:
        # Sync all with local changes
        documents = await document_ops.get_with_local_changes(
            db, product_id=product_id, user_id=current_user.id
        )

    if not documents:
        return SyncDocsResponse(
            success=True,
            files_synced=0,
            errors=["No documents to sync"],
        )

    # Get primary repository for this product
    repos = await repository_ops.get_github_repos_by_product(
        db, user_id=current_user.id, product_id=product_id
    )
    if not repos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No GitHub repositories linked to this product",
        )

    # Use first repo (primary)
    repo = repos[0]

    github_service = GitHubService(preferences.github_token)
    sync_service = DocsSyncService(db, github_service)

    result = await sync_service.sync_to_repo(documents, repo, data.message)

    return SyncDocsResponse(
        success=result.success,
        files_synced=result.files_synced,
        commit_sha=result.commit_sha,
        errors=result.errors,
    )
