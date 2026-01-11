import uuid as uuid_pkg

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.domain import document_ops, preferences_ops, product_ops, repository_ops
from app.models.document import DocumentCreate, DocumentUpdate
from app.models.user import User
from app.schemas.docs import (
    AddChangelogEntryRequest,
    BulkRefreshResponse,
    DocsSyncStatusResponse,
    DocumentGrouped,
    DocumentsGroupedResponse,
    DocumentSyncStatusResponse,
    ImportDocsResponse,
    RefreshDocumentDetailResponse,
    RefreshDocumentResponse,
    SyncDocsRequest,
    SyncDocsResponse,
)
from app.services.docs.changelog_agent import ChangelogAgent
from app.services.docs.document_refresher import DocumentRefresher
from app.services.docs.sync_service import DocsSyncService
from app.services.docs.types import ChangeEntry
from app.services.github import GitHubService

router = APIRouter(prefix="/documents", tags=["documents"])


def _serialize_document(d) -> dict:
    """Serialize a document to a dict for JSON response."""
    return {
        "id": str(d.id),
        "title": d.title,
        "content": d.content,
        "type": d.type,
        "is_pinned": d.is_pinned,
        "folder": d.folder,
        "product_id": str(d.product_id) if d.product_id else None,
        "repository_id": str(d.repository_id) if d.repository_id else None,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
        # Sync tracking fields (Phase 2)
        "github_sha": d.github_sha,
        "github_path": d.github_path,
        "last_synced_at": d.last_synced_at.isoformat() if d.last_synced_at else None,
        "sync_status": d.sync_status,
    }


@router.get("", response_model=list[dict])
async def list_documents(
    product_id: uuid_pkg.UUID | None = Query(None, description="Filter by product"),
    type: str | None = Query(None, description="Filter by type"),
    folder: str | None = Query(None, description="Filter by folder path"),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List documents, optionally filtered by product, type, and folder."""
    if product_id and folder:
        # Use folder-specific query
        docs = await document_ops.get_by_folder(
            db, product_id=product_id, folder_path=folder, user_id=current_user.id
        )
    else:
        docs = await document_ops.get_by_product(
            db,
            user_id=current_user.id,
            product_id=product_id,
            type=type,
            skip=skip,
            limit=limit,
        )
    return [_serialize_document(d) for d in docs]


@router.get("/{document_id}")
async def get_document(
    document_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single document."""
    doc = await document_ops.get_by_user(db, user_id=current_user.id, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return _serialize_document(doc)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(
    data: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new document."""
    doc = await document_ops.create(
        db,
        obj_in=data.model_dump(),
        user_id=current_user.id,
    )
    return _serialize_document(doc)


@router.patch("/{document_id}")
async def update_document(
    document_id: uuid_pkg.UUID,
    data: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a document."""
    doc = await document_ops.get_by_user(db, user_id=current_user.id, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    updated = await document_ops.update(
        db, db_obj=doc, obj_in=data.model_dump(exclude_unset=True)
    )
    return _serialize_document(updated)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document."""
    deleted = await document_ops.delete(db, id=document_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )


# =============================================================================
# Plan Lifecycle Endpoints
# =============================================================================


@router.post("/{document_id}/move-to-executing")
async def move_to_executing(
    document_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move a plan to executing/ folder."""
    doc = await document_ops.get_by_user(db, user_id=current_user.id, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if doc.type != "plan":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only plans can be moved to executing",
        )

    updated = await document_ops.move_to_executing(db, document_id, current_user.id)
    return _serialize_document(updated)


@router.post("/{document_id}/move-to-completed")
async def move_to_completed(
    document_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move a plan to completions/ folder with date prefix."""
    doc = await document_ops.get_by_user(db, user_id=current_user.id, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if doc.type != "plan":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only plans can be moved to completions",
        )

    updated = await document_ops.move_to_completed(db, document_id, current_user.id)
    return _serialize_document(updated)


@router.post("/{document_id}/archive")
async def archive_document(
    document_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move a document to archive/ folder."""
    doc = await document_ops.get_by_user(db, user_id=current_user.id, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    updated = await document_ops.archive(db, document_id, current_user.id)
    return _serialize_document(updated)


# =============================================================================
# Product-scoped Document Endpoints
# =============================================================================


@router.get("/products/{product_id}/grouped", response_model=DocumentsGroupedResponse)
async def get_documents_grouped(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentsGroupedResponse:
    """Get documents grouped by folder."""
    # Verify product exists and user has access
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    grouped = await document_ops.get_by_product_grouped(
        db, product_id=product_id, user_id=current_user.id
    )

    # Convert to response format
    def to_grouped(docs) -> list[DocumentGrouped]:
        return [
            DocumentGrouped(
                id=str(d.id),
                title=d.title or "",
                content=d.content,
                type=d.type,
                is_pinned=d.is_pinned or False,
                folder=d.folder,
                created_at=d.created_at.isoformat(),
                updated_at=d.updated_at.isoformat(),
            )
            for d in docs
        ]

    return DocumentsGroupedResponse(
        changelog=to_grouped(grouped["changelog"]),
        blueprints=to_grouped(grouped["blueprints"]),
        plans=to_grouped(grouped["plans"]),
        executing=to_grouped(grouped["executing"]),
        completions=to_grouped(grouped["completions"]),
        archive=to_grouped(grouped["archive"]),
    )


@router.post("/products/{product_id}/changelog/add-entry")
async def add_changelog_entry(
    product_id: uuid_pkg.UUID,
    data: AddChangelogEntryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add an entry to the changelog (Tier 2 maintenance)."""
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Convert request entries to ChangeEntry dataclasses
    changes = [
        ChangeEntry(category=c.category, description=c.description) for c in data.changes
    ]

    changelog_agent = ChangelogAgent(db, product, None)  # type: ignore[arg-type]
    updated_doc = await changelog_agent.add_entry(data.version, changes)
    return _serialize_document(updated_doc)


# =============================================================================
# GitHub Sync Endpoints (Phase 2)
# =============================================================================


@router.post("/products/{product_id}/import-docs", response_model=ImportDocsResponse)
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


@router.get("/products/{product_id}/docs-sync-status", response_model=DocsSyncStatusResponse)
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


@router.post("/{document_id}/pull-remote")
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

    return _serialize_document(updated_doc)


@router.post("/products/{product_id}/sync-docs", response_model=SyncDocsResponse)
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


# =============================================================================
# Document Refresh Endpoints (Phase 7)
# =============================================================================


@router.post("/{document_id}/refresh", response_model=RefreshDocumentResponse)
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


@router.post("/products/{product_id}/refresh-all-docs", response_model=BulkRefreshResponse)
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
