"""DB integration tests for WorkItemOperations.

Tests real SQL against PostgreSQL via rollback fixture.
Covers: create, product scoping, status/type filters, update, delete.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.work_item_operations import work_item_ops


class TestWorkItemCRUD:
    """Test work item create, read, update, delete."""

    async def test_create_work_item(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Can create a work item linked to a product."""
        item = await work_item_ops.create(
            db_session,
            obj_in={
                "title": "Implement dark mode",
                "description": "Add theme toggle",
                "type": "feature",
                "status": "todo",
                "priority": 1,
                "product_id": test_product.id,
            },
            created_by_user_id=test_user.id,
        )

        assert item.id is not None
        assert item.title == "Implement dark mode"
        assert item.type == "feature"
        assert item.status == "todo"
        assert item.priority == 1
        assert item.created_by_user_id == test_user.id

    async def test_get_by_product(
        self, db_session: AsyncSession, test_product, test_work_item
    ):
        """get_by_product returns work items for the product."""
        items = await work_item_ops.get_by_product(db_session, test_product.id)
        item_ids = [i.id for i in items]
        assert test_work_item.id in item_ids


class TestWorkItemFilters:
    """Test status and type filtering."""

    async def test_status_filter(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Can filter work items by status."""
        # Create items with different statuses
        await work_item_ops.create(
            db_session,
            obj_in={
                "title": "Done task",
                "type": "fix",
                "status": "done",
                "product_id": test_product.id,
            },
            created_by_user_id=test_user.id,
        )
        await work_item_ops.create(
            db_session,
            obj_in={
                "title": "Todo task",
                "type": "fix",
                "status": "todo",
                "product_id": test_product.id,
            },
            created_by_user_id=test_user.id,
        )

        done_items = await work_item_ops.get_by_product(
            db_session, test_product.id, status="done"
        )
        assert all(i.status == "done" for i in done_items)
        assert len(done_items) >= 1

    async def test_type_filter(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Can filter work items by type."""
        await work_item_ops.create(
            db_session,
            obj_in={
                "title": "Refactor auth",
                "type": "refactor",
                "status": "todo",
                "product_id": test_product.id,
            },
            created_by_user_id=test_user.id,
        )

        refactors = await work_item_ops.get_by_product(
            db_session, test_product.id, type="refactor"
        )
        assert all(i.type == "refactor" for i in refactors)
        assert len(refactors) >= 1


class TestWorkItemMutations:
    """Test work item update and delete."""

    async def test_update_work_item(
        self, db_session: AsyncSession, test_work_item
    ):
        """Can update work item fields."""
        updated = await work_item_ops.update(
            db_session, test_work_item, {"status": "in_progress", "priority": 2}
        )
        assert updated.status == "in_progress"
        assert updated.priority == 2

    async def test_delete_work_item(
        self, db_session: AsyncSession, test_work_item
    ):
        """Can soft-delete a work item."""
        deleted = await work_item_ops.delete(db_session, test_work_item)
        assert deleted is True

        found = await work_item_ops.get(db_session, test_work_item.id)
        assert found is not None
        assert found.status == "deleted"
        assert found.deleted_at is not None
