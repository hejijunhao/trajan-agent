import uuid as uuid_pkg

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.domain import document_ops
from app.models.document import DocumentCreate, DocumentUpdate
from app.models.user import User

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[dict])
async def list_documents(
    product_id: uuid_pkg.UUID | None = Query(None, description="Filter by product"),
    type: str | None = Query(None, description="Filter by type"),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List documents, optionally filtered by product."""
    docs = await document_ops.get_by_product(
        db,
        user_id=current_user.id,
        product_id=product_id,
        type=type,
        skip=skip,
        limit=limit,
    )
    return [
        {
            "id": str(d.id),
            "title": d.title,
            "content": d.content,
            "type": d.type,
            "is_pinned": d.is_pinned,
            "product_id": str(d.product_id) if d.product_id else None,
            "repository_id": str(d.repository_id) if d.repository_id else None,
            "created_at": d.created_at.isoformat(),
            "updated_at": d.updated_at.isoformat(),
        }
        for d in docs
    ]


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
    return {
        "id": str(doc.id),
        "title": doc.title,
        "content": doc.content,
        "type": doc.type,
        "is_pinned": doc.is_pinned,
        "product_id": str(doc.product_id) if doc.product_id else None,
        "repository_id": str(doc.repository_id) if doc.repository_id else None,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


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
    return {
        "id": str(doc.id),
        "title": doc.title,
        "content": doc.content,
        "type": doc.type,
        "is_pinned": doc.is_pinned,
        "product_id": str(doc.product_id) if doc.product_id else None,
        "repository_id": str(doc.repository_id) if doc.repository_id else None,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


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
    return {
        "id": str(updated.id),
        "title": updated.title,
        "content": updated.content,
        "type": updated.type,
        "is_pinned": updated.is_pinned,
        "product_id": str(updated.product_id) if updated.product_id else None,
        "repository_id": str(updated.repository_id) if updated.repository_id else None,
        "created_at": updated.created_at.isoformat(),
        "updated_at": updated.updated_at.isoformat(),
    }


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
