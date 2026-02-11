"""Basic CRUD operations and product-scoped document endpoints."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SubscriptionContext,
    check_product_editor_access,
    get_current_user,
    get_db_with_rls,
    get_product_access,
    require_active_subscription,
)
from app.domain import document_ops, product_ops
from app.models.document import DocumentCreate, DocumentUpdate
from app.models.user import User
from app.schemas.docs import (
    AddChangelogEntryRequest,
    DocumentGrouped,
    DocumentsGroupedResponse,
)
from app.services.docs.changelog_agent import ChangelogAgent
from app.services.docs.types import ChangeEntry


def serialize_document(d) -> dict:
    """Serialize a document to a dict for JSON response."""
    return {
        "id": str(d.id),
        "title": d.title,
        "content": d.content,
        "type": d.type,
        "is_pinned": d.is_pinned,
        "is_generated": d.is_generated,  # True = AI-generated, False = imported
        "folder": d.folder,
        "product_id": str(d.product_id) if d.product_id else None,
        "repository_id": str(d.repository_id) if d.repository_id else None,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
        # Section-based organization (for Trajan Docs sectioned view)
        "section": d.section,
        "subsection": d.subsection,
        # Sync tracking fields (Phase 2)
        "github_sha": d.github_sha,
        "github_path": d.github_path,
        "last_synced_at": d.last_synced_at.isoformat() if d.last_synced_at else None,
        "sync_status": d.sync_status,
    }


async def list_documents(
    product_id: uuid_pkg.UUID | None = Query(None, description="Filter by product"),
    doc_type: str | None = Query(None, alias="type", description="Filter by type"),
    folder: str | None = Query(None, description="Filter by folder path"),
    is_generated: bool | None = Query(
        None, description="Filter by origin: true=AI-generated, false=imported"
    ),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """List documents, optionally filtered by product, type, folder, and origin."""
    if not product_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="product_id is required",
        )

    # Verify product access (RLS enforces, but explicit check is clearer)
    await get_product_access(product_id, db, current_user)

    if folder:
        # Use folder-specific query
        docs = await document_ops.get_by_folder(db, product_id=product_id, folder_path=folder)
    else:
        docs = await document_ops.get_by_product(
            db,
            product_id=product_id,
            doc_type=doc_type,
            is_generated=is_generated,
            skip=skip,
            limit=limit,
        )
    return [serialize_document(d) for d in docs]


async def get_document(
    document_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Get a single document. RLS enforces product access."""
    doc = await document_ops.get(db, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Verify product access (RLS enforces, but explicit check is clearer)
    if doc.product_id:
        await get_product_access(doc.product_id, db, current_user)

    return serialize_document(doc)


async def create_document(
    data: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
    _sub: SubscriptionContext = Depends(require_active_subscription),
):
    """Create a new document. Requires Editor or Admin access to the product.

    Documents created via API are marked as is_generated=True since they're
    created within Trajan (not imported from a repository).
    """
    # Check product access
    if data.product_id:
        await check_product_editor_access(db, data.product_id, current_user.id)

    # Documents created in Trajan are marked as generated
    doc_data = data.model_dump()
    doc_data["is_generated"] = True

    doc = await document_ops.create(
        db,
        obj_in=doc_data,
        created_by_user_id=current_user.id,
    )
    return serialize_document(doc)


async def update_document(
    document_id: uuid_pkg.UUID,
    data: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
    _sub: SubscriptionContext = Depends(require_active_subscription),
):
    """Update a document. Requires Editor or Admin access to the product."""
    doc = await document_ops.get(db, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Check product access
    if doc.product_id:
        await check_product_editor_access(db, doc.product_id, current_user.id)

    updated = await document_ops.update(db, db_obj=doc, obj_in=data.model_dump(exclude_unset=True))
    return serialize_document(updated)


async def delete_document(
    document_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
    _sub: SubscriptionContext = Depends(require_active_subscription),
):
    """Delete a document. Requires Editor or Admin access to the product."""
    # Get document first to check product access
    doc = await document_ops.get(db, id=document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Check product access
    if doc.product_id:
        await check_product_editor_access(db, doc.product_id, current_user.id)

    await document_ops.delete(db, id=document_id)


# =============================================================================
# Product-scoped Document Endpoints
# =============================================================================


async def get_documents_grouped(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> DocumentsGroupedResponse:
    """Get documents grouped by folder. RLS enforces product access."""
    # Verify product access (RLS enforces, but explicit check is clearer)
    await get_product_access(product_id, db, current_user)

    # Verify product exists
    product = await product_ops.get(db, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    grouped = await document_ops.get_by_product_grouped(db, product_id=product_id)

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
                section=d.section,
                subsection=d.subsection,
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


async def add_changelog_entry(
    product_id: uuid_pkg.UUID,
    data: AddChangelogEntryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
    _sub: SubscriptionContext = Depends(require_active_subscription),
):
    """Add an entry to the changelog. Requires Editor or Admin access to the product."""
    # Check product access first
    await check_product_editor_access(db, product_id, current_user.id)

    product = await product_ops.get(db, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Convert request entries to ChangeEntry dataclasses
    changes = [ChangeEntry(category=c.category, description=c.description) for c in data.changes]

    changelog_agent = ChangelogAgent(db, product, current_user.id)
    updated_doc = await changelog_agent.add_entry(data.version, changes)
    return serialize_document(updated_doc)


async def delete_all_generated_documents(
    product_id: uuid_pkg.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
    _sub: SubscriptionContext = Depends(require_active_subscription),
) -> dict:
    """Delete all AI-generated documents for a product.

    This bulk operation removes all documents where is_generated=True.
    Repository-imported documents are preserved.
    Requires Editor or Admin access to the product.
    """
    # Check product access first
    await check_product_editor_access(db, product_id, current_user.id)

    # Verify product exists
    product = await product_ops.get(db, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    deleted_count = await document_ops.delete_by_product_generated(db, product_id)
    return {"deleted_count": deleted_count}
