import uuid as uuid_pkg
from datetime import UTC, datetime

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

    async def get_by_product_grouped(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> dict[str, list[Document]]:
        """Get documents grouped by folder path."""
        docs = await self.get_by_product(db, user_id, product_id)

        grouped: dict[str, list[Document]] = {
            "changelog": [],
            "blueprints": [],
            "plans": [],
            "executing": [],
            "completions": [],
            "archive": [],
        }

        for doc in docs:
            folder_path = doc.folder.get("path") if doc.folder else None

            if doc.type == "changelog":
                grouped["changelog"].append(doc)
            elif folder_path:
                # Handle nested paths (e.g., "blueprints/backend" -> "blueprints")
                root_folder = folder_path.split("/")[0]
                if root_folder in grouped:
                    grouped[root_folder].append(doc)
            else:
                # Default to blueprints for docs without folder
                grouped["blueprints"].append(doc)

        return grouped

    async def get_by_folder(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        folder_path: str,
        user_id: uuid_pkg.UUID,
    ) -> list[Document]:
        """Get documents in a specific folder."""
        result = await db.execute(
            select(Document)
            .where(Document.product_id == product_id)
            .where(Document.user_id == user_id)
            .where(Document.folder["path"].astext == folder_path)
            .order_by(Document.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_changelog(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> Document | None:
        """Get the changelog document for a product."""
        result = await db.execute(
            select(Document)
            .where(Document.product_id == product_id)
            .where(Document.user_id == user_id)
            .where(Document.type == "changelog")
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def move_to_folder(
        self,
        db: AsyncSession,
        document_id: uuid_pkg.UUID,
        new_folder: str,
        user_id: uuid_pkg.UUID,
    ) -> Document | None:
        """Move document to a new folder."""
        doc = await self.get_by_user(db, user_id, document_id)
        if not doc:
            return None

        doc.folder = {"path": new_folder}
        doc.updated_at = datetime.now(UTC)
        # Mark as having local changes if it was synced
        if doc.sync_status == "synced":
            doc.sync_status = "local_changes"
        await db.commit()
        await db.refresh(doc)
        return doc

    async def get_synced_documents(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> list[Document]:
        """Get documents that have been synced with GitHub."""
        result = await db.execute(
            select(Document)
            .where(Document.product_id == product_id)
            .where(Document.user_id == user_id)
            .where(Document.github_path.isnot(None))
            .order_by(Document.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_with_local_changes(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> list[Document]:
        """Get documents with unsynchronized local changes."""
        result = await db.execute(
            select(Document)
            .where(Document.product_id == product_id)
            .where(Document.user_id == user_id)
            .where(Document.sync_status == "local_changes")
            .order_by(Document.updated_at.desc())
        )
        return list(result.scalars().all())

    async def mark_local_changes(
        self,
        db: AsyncSession,
        document_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> Document | None:
        """Mark a document as having local changes (for sync tracking)."""
        doc = await self.get_by_user(db, user_id, document_id)
        if not doc:
            return None

        if doc.github_path:  # Only track if it's a synced document
            doc.sync_status = "local_changes"
            await db.commit()
            await db.refresh(doc)
        return doc


document_ops = DocumentOperations()
