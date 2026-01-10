import uuid as uuid_pkg
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
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

    doc.folder = {"path": "executing"}
    doc.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(doc)
    return _serialize_document(doc)


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

    # Include date in folder path
    date_prefix = datetime.now(UTC).strftime("%Y-%m-%d")
    doc.folder = {"path": f"completions/{date_prefix}"}
    doc.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(doc)
    return _serialize_document(doc)


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

    doc.folder = {"path": "archive"}
    doc.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(doc)
    return _serialize_document(doc)


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
