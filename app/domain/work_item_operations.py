import uuid as uuid_pkg

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_item import WorkItem


class WorkItemOperations:
    """CRUD operations for WorkItem model.

    Work items are product-scoped resources. Visibility is controlled by Product
    access (RLS), not by user ownership. The created_by_user_id tracks who
    created the work item (for audit trail).
    """

    async def get(
        self,
        db: AsyncSession,
        work_item_id: uuid_pkg.UUID,
    ) -> WorkItem | None:
        """Get a work item by ID (RLS enforces product access)."""
        statement = select(WorkItem).where(WorkItem.id == work_item_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_product(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        status: str | None = None,
        type: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[WorkItem]:
        """Get work items for a product with optional filtering by status and type.

        RLS enforces that the caller has product access.
        """
        statement = select(WorkItem).where(WorkItem.product_id == product_id)

        if status:
            statement = statement.where(WorkItem.status == status)
        if type:
            statement = statement.where(WorkItem.type == type)

        statement = statement.order_by(WorkItem.created_at.desc()).offset(skip).limit(limit)

        result = await db.execute(statement)
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        obj_in: dict,
        created_by_user_id: uuid_pkg.UUID,
    ) -> WorkItem:
        """Create a new work item.

        The created_by_user_id tracks who created the work item (audit trail).
        Caller must verify product editor access before calling.
        """
        db_obj = WorkItem(**obj_in, created_by_user_id=created_by_user_id)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        db_obj: WorkItem,
        obj_in: dict,
    ) -> WorkItem:
        """Update an existing work item.

        Caller must verify product editor access before calling.
        """
        for field, value in obj_in.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def delete(
        self,
        db: AsyncSession,
        work_item: WorkItem,
    ) -> bool:
        """Delete a work item.

        Caller must verify product editor access before calling.
        """
        await db.delete(work_item)
        await db.flush()
        return True


work_item_ops = WorkItemOperations()
