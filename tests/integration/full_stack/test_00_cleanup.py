"""Cleanup Infrastructure Verification.

Validates that TestCleanup correctly removes a full entity tree
and that CleanupError is raised when operations fail.

Runs as test_00 so it executes first — if cleanup is broken,
fail fast before creating resources that can't be cleaned up.

Runs against REAL infrastructure (direct DB connection).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_info import AppInfo
from app.models.document import Document
from app.models.document_section import DocumentSection
from app.models.organization import Organization, OrganizationMember
from app.models.product import Product
from app.models.repository import Repository
from app.models.subscription import Subscription
from app.models.user import User
from app.models.work_item import WorkItem
from tests.helpers.cleanup import CleanupError, TestCleanup
from tests.helpers.tracker import ResourceTracker

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_user() -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=f"__test_cleanup_{uid.hex[:8]}@test.local",
        display_name="Cleanup Test User",
        created_at=datetime.now(UTC),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCleanupInfrastructure:
    """Verify that TestCleanup correctly removes a full entity tree."""

    @pytest.mark.full_stack
    async def test_full_entity_tree_cleanup(self, integration_db: AsyncSession):
        """Create org → product → repo + doc + work_item + app_info,
        run cleanup, verify nothing remains in the DB.

        Uses a local ResourceTracker (separate from the session tracker)
        so this test is self-contained.
        """
        tracker = ResourceTracker()

        # ── Build entity tree directly in DB ──────────────────────────
        user = _make_user()
        integration_db.add(user)
        await integration_db.flush()

        org = Organization(
            id=uuid.uuid4(),
            name="[TEST] Cleanup Verification Org",
            slug=f"cleanup-verify-{uuid.uuid4().hex[:8]}",
            owner_id=user.id,
        )
        integration_db.add(org)
        await integration_db.flush()

        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role="owner",
        )
        integration_db.add(member)

        sub = Subscription(
            id=uuid.uuid4(),
            organization_id=org.id,
            plan_tier="indie",
            status="active",
        )
        integration_db.add(sub)
        await integration_db.flush()

        product = Product(
            id=uuid.uuid4(),
            name="[TEST] Cleanup Product",
            slug=f"cleanup-product-{uuid.uuid4().hex[:8]}",
            organization_id=org.id,
            user_id=user.id,
        )
        integration_db.add(product)
        await integration_db.flush()

        repo = Repository(
            id=uuid.uuid4(),
            name="cleanup-repo",
            full_name="test/cleanup-repo",
            product_id=product.id,
            github_id=888888,
            url="https://github.com/test/cleanup-repo",
            default_branch="main",
            imported_by_user_id=user.id,
        )
        integration_db.add(repo)

        doc = Document(
            id=uuid.uuid4(),
            title="Cleanup Doc",
            content="# Test",
            type="note",
            product_id=product.id,
            created_by_user_id=user.id,
        )
        integration_db.add(doc)

        work_item = WorkItem(
            id=uuid.uuid4(),
            title="Cleanup Task",
            type="feature",
            status="todo",
            product_id=product.id,
            created_by_user_id=user.id,
        )
        integration_db.add(work_item)

        app_info = AppInfo(
            id=uuid.uuid4(),
            user_id=user.id,
            product_id=product.id,
            key="CLEANUP_VAR",
            value="test",
            category="env",
        )
        integration_db.add(app_info)

        section = DocumentSection(
            id=uuid.uuid4(),
            product_id=product.id,
            name="Cleanup Section",
            slug="cleanup-section",
            position=0,
        )
        integration_db.add(section)
        await integration_db.flush()

        # Collect IDs for post-cleanup verification
        ids = {
            "product": product.id,
            "org": org.id,
            "sub": sub.id,
            "repo": repo.id,
            "doc": doc.id,
            "work_item": work_item.id,
            "app_info": app_info.id,
            "section": section.id,
        }

        # ── Register in tracker ───────────────────────────────────────
        tracker.register_product(product.id)
        tracker.register_repository(repo.id)
        tracker.register_document(doc.id)
        tracker.register_work_item(work_item.id)
        tracker.register_app_info(app_info.id)
        tracker.register_org(org.id)
        # Note: user NOT tracked — avoids Supabase auth deletion for DB-only user

        # ── Run cleanup ───────────────────────────────────────────────
        await TestCleanup().cleanup_all(tracker, integration_db)

        # ── Verify everything is gone ─────────────────────────────────
        checks = [
            ("Product", Product, ids["product"]),
            ("Organization", Organization, ids["org"]),
            ("Subscription", Subscription, ids["sub"]),
            ("Repository", Repository, ids["repo"]),
            ("Document", Document, ids["doc"]),
            ("WorkItem", WorkItem, ids["work_item"]),
            ("AppInfo", AppInfo, ids["app_info"]),
            ("DocumentSection", DocumentSection, ids["section"]),
        ]

        for label, model, eid in checks:
            result = await integration_db.execute(select(model).where(model.id == eid))
            assert result.scalar_one_or_none() is None, (
                f"CLEANUP LEAK: {label} {eid} still exists after cleanup"
            )

        # Clean up the user (not tracked to avoid Supabase calls)
        from sqlalchemy import delete

        await integration_db.execute(delete(User).where(User.id == user.id))
        await integration_db.commit()

    @pytest.mark.full_stack
    async def test_tracker_summary_reflects_all_types(self):
        """ResourceTracker.summary includes non-zero child counts."""
        tracker = ResourceTracker()
        fake_id = uuid.uuid4()

        # Base types always shown
        assert "0 users" in tracker.summary
        assert "0 orgs" in tracker.summary
        assert "0 products" in tracker.summary

        # Child types hidden when empty
        assert "repos" not in tracker.summary

        # Register some child resources
        tracker.register_repository(fake_id)
        tracker.register_document(fake_id)
        tracker.register_feedback(fake_id)

        assert "1 repos" in tracker.summary
        assert "1 docs" in tracker.summary
        assert "1 feedback" in tracker.summary
        assert tracker.total_count == 3

    @pytest.mark.full_stack
    async def test_cleanup_raises_on_failure(self, integration_db: AsyncSession):
        """CleanupError is raised with a summary when a cleanup operation fails."""
        tracker = ResourceTracker()
        # Register a product that doesn't exist — the cascade delete
        # won't fail (DELETE with no matching rows is fine), so we mock a failure.
        tracker.register_product(uuid.uuid4())

        with (
            patch.object(
                TestCleanup,
                "_delete_product_cascade",
                new_callable=AsyncMock,
                side_effect=lambda _db, pid, failures: failures.append(
                    f"Product {pid}: simulated failure"
                ),
            ),
            pytest.raises(CleanupError, match="1 cleanup operation.*failed"),
        ):
            await TestCleanup().cleanup_all(tracker, integration_db)
