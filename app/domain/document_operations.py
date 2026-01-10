import uuid as uuid_pkg

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.base_operations import BaseOperations
from app.models.document import Document


class DocumentOperations(BaseOperations[Document]):
    """CRUD operations for Document model."""

    def __init__(self):
        super().__init__(Document)

    async def get_by_product(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        product_id: uuid_pkg.UUID | None = None,
        type: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Document]:
        """Get documents with optional filtering by product and type."""
        statement = select(Document).where(Document.user_id == user_id)

        if product_id:
            statement = statement.where(Document.product_id == product_id)
        if type:
            statement = statement.where(Document.type == type)

        statement = (
            statement.order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await db.execute(statement)
        return list(result.scalars().all())


document_ops = DocumentOperations()
