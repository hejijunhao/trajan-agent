"""Plan lifecycle endpoints — state transitions for plan documents."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.documents.crud import serialize_document
from app.core.database import get_db
from app.domain import document_ops
from app.models.user import User


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
    return serialize_document(updated)


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
    return serialize_document(updated)


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
    return serialize_document(updated)
