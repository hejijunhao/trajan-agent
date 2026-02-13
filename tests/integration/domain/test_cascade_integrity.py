"""Cascade delete and referential integrity tests.

Verifies that deleting parent entities correctly cascades to children
at every level of the hierarchy, and that SET NULL foreign keys are
handled correctly for soft references.

Uses raw SQL DELETE statements to test the *database-level* cascade
configuration (ondelete="CASCADE" / "SET NULL"), bypassing the ORM's
relationship handling. This matches production behavior where parent
and child entities are typically in different sessions.

Cascade chain:
  Organization → Product, Subscription, OrganizationMember, BillingEvent
  Product → Repository, WorkItem, Document, AppInfo, ProductAccess, DocumentSection
  DocumentSection → DocumentSubsection
  User → (SET NULL on Product.lead_user_id, BillingEvent.actor_user_id)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.document_operations import document_ops
from app.domain.organization_operations import organization_ops
from app.domain.product_access_operations import product_access_ops
from app.domain.product_operations import product_ops
from app.domain.repository_operations import repository_ops
from app.domain.subscription_operations import subscription_ops
from app.domain.work_item_operations import work_item_ops
from app.models.app_info import AppInfo
from app.models.document import Document
from app.models.document_section import DocumentSection, DocumentSubsection
from app.models.organization import Organization, OrganizationMember
from app.models.product import Product
from app.models.product_access import ProductAccess
from app.models.repository import Repository
from app.models.subscription import Subscription
from app.models.user import User
from app.models.work_item import WorkItem

# ─────────────────────────────────────────────────────────────────────────────
# Organization cascade
# ─────────────────────────────────────────────────────────────────────────────


class TestOrganizationCascade:
    """Deleting an organization cascades to subscription, members, and products."""

    async def test_org_delete_cascades_subscription(
        self, db_session: AsyncSession, test_user
    ):
        """Deleting an org removes its subscription."""
        org = await organization_ops.create(
            db_session, name="Cascade Org", owner_id=test_user.id
        )
        org_id = org.id
        sub = await subscription_ops.get_by_org(db_session, org_id)
        assert sub is not None
        sub_id = sub.id

        # Use raw SQL DELETE to test DB-level cascade (not ORM cascade)
        db_session.expunge_all()
        await db_session.execute(delete(Organization).where(Organization.id == org_id))
        await db_session.flush()

        # Subscription should be gone via DB cascade
        result = await db_session.execute(
            select(Subscription).where(Subscription.id == sub_id)
        )
        assert result.scalar_one_or_none() is None

    async def test_org_delete_cascades_members(
        self, db_session: AsyncSession, test_user
    ):
        """Deleting an org removes all its member records."""
        org = await organization_ops.create(
            db_session, name="Member Cascade Org", owner_id=test_user.id
        )
        org_id = org.id

        # Verify owner membership exists
        is_member = await organization_ops.is_member(db_session, org_id, test_user.id)
        assert is_member is True

        db_session.expunge_all()
        await db_session.execute(delete(Organization).where(Organization.id == org_id))
        await db_session.flush()

        # Membership should be gone
        result = await db_session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id
            )
        )
        assert result.scalar_one_or_none() is None

    async def test_org_delete_cascades_products(
        self, db_session: AsyncSession, test_user
    ):
        """Deleting an org removes all its products via DB-level CASCADE."""
        org = await organization_ops.create(
            db_session, name="Product Cascade Org", owner_id=test_user.id
        )
        org_id = org.id

        # Activate subscription so product creation succeeds
        sub = await subscription_ops.get_by_org(db_session, org_id)
        await subscription_ops.update(
            db_session, sub, {"plan_tier": "indie", "status": "active"}
        )

        product = await product_ops.create(
            db_session,
            obj_in={"name": "Cascade Product", "organization_id": org_id},
            user_id=test_user.id,
        )
        product_id = product.id

        # Raw SQL DELETE bypasses ORM relationship handling,
        # letting ondelete="CASCADE" on products.organization_id fire.
        db_session.expunge_all()
        await db_session.execute(delete(Organization).where(Organization.id == org_id))
        await db_session.flush()

        # Product should be gone
        result = await db_session.execute(
            select(Product).where(Product.id == product_id)
        )
        assert result.scalar_one_or_none() is None


# ─────────────────────────────────────────────────────────────────────────────
# Product cascade (full child hierarchy)
# ─────────────────────────────────────────────────────────────────────────────


class TestProductCascade:
    """Deleting a product cascades to all 6 child entity types."""

    async def test_product_delete_cascades_all_children(
        self,
        db_session: AsyncSession,
        test_user,
        test_org,
        test_subscription,  # noqa: ARG002
    ):
        """Deleting a product removes repos, docs, work items, app info,
        access entries, and document sections."""
        product = await product_ops.create(
            db_session,
            obj_in={"name": "Full Cascade Product", "organization_id": test_org.id},
            user_id=test_user.id,
        )
        pid = product.id

        # Create one of each child type
        repo = await repository_ops.create(
            db_session,
            obj_in={
                "name": "cascade-repo",
                "full_name": "test/cascade-repo",
                "product_id": pid,
                "github_id": 999999,
                "url": "https://github.com/test/cascade-repo",
                "default_branch": "main",
            },
            imported_by_user_id=test_user.id,
        )

        doc = await document_ops.create(
            db_session,
            obj_in={
                "title": "Cascade Doc",
                "content": "# Test",
                "type": "note",
                "product_id": pid,
            },
            created_by_user_id=test_user.id,
        )

        work_item = await work_item_ops.create(
            db_session,
            obj_in={
                "title": "Cascade Task",
                "type": "feature",
                "status": "todo",
                "product_id": pid,
            },
            created_by_user_id=test_user.id,
        )

        app_info = AppInfo(
            user_id=test_user.id,
            product_id=pid,
            key="CASCADE_VAR",
            value="test",
            category="env",
        )
        db_session.add(app_info)
        await db_session.flush()

        access = await product_access_ops.set_access(
            db_session, pid, test_user.id, "editor"
        )

        section = DocumentSection(
            product_id=pid,
            name="Cascade Section",
            slug="cascade",
            position=0,
        )
        db_session.add(section)
        await db_session.flush()

        # Collect IDs for post-delete verification
        ids = {
            "repo": repo.id,
            "doc": doc.id,
            "work_item": work_item.id,
            "app_info": app_info.id,
            "access": access.id,
            "section": section.id,
        }

        # Delete the product (ORM cascade works here because Product has
        # cascade="all, delete-orphan" on all child relationships)
        await product_ops.delete(db_session, id=pid, user_id=test_user.id)

        # Verify all children are gone
        for label, (model, eid) in {
            "repository": (Repository, ids["repo"]),
            "document": (Document, ids["doc"]),
            "work_item": (WorkItem, ids["work_item"]),
            "app_info": (AppInfo, ids["app_info"]),
            "product_access": (ProductAccess, ids["access"]),
            "document_section": (DocumentSection, ids["section"]),
        }.items():
            result = await db_session.execute(select(model).where(model.id == eid))
            assert result.scalar_one_or_none() is None, (
                f"{label} with id {eid} should have been cascade-deleted"
            )


# ─────────────────────────────────────────────────────────────────────────────
# DocumentSection → Subsection cascade
# ─────────────────────────────────────────────────────────────────────────────


class TestDocumentSectionCascade:
    """Deleting a section cascades to its subsections."""

    async def test_section_delete_cascades_subsections(
        self,
        db_session: AsyncSession,
        test_product,
    ):
        """Deleting a DocumentSection removes all its DocumentSubsections."""
        section = DocumentSection(
            product_id=test_product.id,
            name="Parent Section",
            slug="parent",
            position=0,
        )
        db_session.add(section)
        await db_session.flush()
        await db_session.refresh(section)

        sub1 = DocumentSubsection(
            section_id=section.id,
            name="Child 1",
            slug="child-1",
            position=0,
        )
        sub2 = DocumentSubsection(
            section_id=section.id,
            name="Child 2",
            slug="child-2",
            position=1,
        )
        db_session.add_all([sub1, sub2])
        await db_session.flush()

        sub1_id, sub2_id = sub1.id, sub2.id

        # Delete the parent section
        await db_session.delete(section)
        await db_session.flush()

        # Subsections should be gone
        for sub_id in (sub1_id, sub2_id):
            result = await db_session.execute(
                select(DocumentSubsection).where(DocumentSubsection.id == sub_id)
            )
            assert result.scalar_one_or_none() is None


# ─────────────────────────────────────────────────────────────────────────────
# Multi-level cascade (Org → Product → children)
# ─────────────────────────────────────────────────────────────────────────────


class TestMultiLevelCascade:
    """Verify cascades propagate through multiple levels.

    NOTE: Only some child FKs have DB-level ondelete="CASCADE" (e.g.,
    ProductAccess, OrganizationMember). Others (Repository, Document) use
    ORM-level cascade="all, delete-orphan" on the Product relationship.
    These tests use entities with DB-level CASCADE to verify the full chain.
    """

    async def test_org_delete_cascades_through_products_to_access(
        self, db_session: AsyncSession, test_user
    ):
        """Org delete → Product delete → ProductAccess delete (3 levels deep).

        Uses ProductAccess because it has ondelete="CASCADE" on both
        product_id and user_id FKs, so the full DB cascade chain works.
        """
        org = await organization_ops.create(
            db_session, name="Deep Cascade Org", owner_id=test_user.id
        )
        org_id = org.id
        sub = await subscription_ops.get_by_org(db_session, org_id)
        await subscription_ops.update(
            db_session, sub, {"plan_tier": "indie", "status": "active"}
        )

        # Create a second user to be a product collaborator
        second = User(
            id=uuid.uuid4(),
            email=f"__test_deep_{uuid.uuid4().hex[:8]}@example.com",
            display_name="Deep User",
            created_at=datetime.now(UTC),
        )
        db_session.add(second)
        await db_session.flush()

        product = await product_ops.create(
            db_session,
            obj_in={"name": "Deep Product", "organization_id": org_id},
            user_id=test_user.id,
        )

        # Grant access (ProductAccess has DB-level ondelete="CASCADE" on product_id)
        access = await product_access_ops.set_access(
            db_session, product.id, second.id, "editor"
        )
        access_id = access.id
        product_id = product.id

        # Raw SQL DELETE to test the full DB cascade chain:
        # organizations → products (CASCADE) → product_access (CASCADE)
        db_session.expunge_all()
        await db_session.execute(delete(Organization).where(Organization.id == org_id))
        await db_session.flush()

        # Product should be gone (level 2)
        result = await db_session.execute(
            select(Product).where(Product.id == product_id)
        )
        assert result.scalar_one_or_none() is None

        # ProductAccess should be gone (level 3)
        result = await db_session.execute(
            select(ProductAccess).where(ProductAccess.id == access_id)
        )
        assert result.scalar_one_or_none() is None


# ─────────────────────────────────────────────────────────────────────────────
# SET NULL behavior
# ─────────────────────────────────────────────────────────────────────────────


class TestSetNullBehavior:
    """Verify that soft FK references use SET NULL instead of CASCADE."""

    async def test_lead_user_delete_sets_null(
        self,
        db_session: AsyncSession,
        test_user,
        test_org,
        test_subscription,  # noqa: ARG002
    ):
        """Deleting the lead_user sets Product.lead_user_id to NULL, not delete the product."""
        # Create a dedicated lead user
        lead = User(
            id=uuid.uuid4(),
            email=f"__test_lead_{uuid.uuid4().hex[:8]}@example.com",
            display_name="Lead User",
            created_at=datetime.now(UTC),
        )
        db_session.add(lead)
        await db_session.flush()

        product = await product_ops.create(
            db_session,
            obj_in={
                "name": "Lead Test Product",
                "organization_id": test_org.id,
                "lead_user_id": lead.id,
            },
            user_id=test_user.id,
        )
        assert product.lead_user_id == lead.id
        product_id = product.id
        lead_id = lead.id

        # Raw SQL DELETE to test DB-level ondelete="SET NULL"
        db_session.expunge_all()
        await db_session.execute(delete(User).where(User.id == lead_id))
        await db_session.flush()

        # Product should still exist but lead_user_id should be NULL
        result = await db_session.execute(
            select(Product).where(Product.id == product_id)
        )
        refreshed = result.scalar_one_or_none()
        assert refreshed is not None
        assert refreshed.lead_user_id is None

    async def test_user_delete_cascades_product_access(
        self,
        db_session: AsyncSession,
        test_product,
    ):
        """Deleting a user cascades to their ProductAccess entries."""
        collab = User(
            id=uuid.uuid4(),
            email=f"__test_collab_{uuid.uuid4().hex[:8]}@example.com",
            display_name="Collaborator",
            created_at=datetime.now(UTC),
        )
        db_session.add(collab)
        await db_session.flush()

        access = await product_access_ops.set_access(
            db_session, test_product.id, collab.id, "editor"
        )
        access_id = access.id
        collab_id = collab.id
        product_id = test_product.id

        # Raw SQL DELETE to test DB-level ondelete="CASCADE" on product_access.user_id
        db_session.expunge_all()
        await db_session.execute(delete(User).where(User.id == collab_id))
        await db_session.flush()

        # Access entry should be cascade-deleted
        result = await db_session.execute(
            select(ProductAccess).where(ProductAccess.id == access_id)
        )
        assert result.scalar_one_or_none() is None

        # Product should still exist
        result = await db_session.execute(
            select(Product).where(Product.id == product_id)
        )
        assert result.scalar_one_or_none() is not None
