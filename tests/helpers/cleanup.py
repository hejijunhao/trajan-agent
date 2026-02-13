"""FK-aware cascade cleanup for full-stack integration tests.

Deletes test resources in reverse FK-dependency order to avoid
constraint violations. Used by the session-level cleanup fixture.

Failures are collected (not raised) during cleanup so all phases run,
then a single ``CleanupError`` is raised with a summary if anything failed.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_info import AppInfo
from app.models.custom_doc_job import CustomDocJob
from app.models.dashboard_shipped_summary import DashboardShippedSummary
from app.models.document import Document
from app.models.document_section import DocumentSection, DocumentSubsection
from app.models.feedback import Feedback
from app.models.organization import Organization, OrganizationMember
from app.models.product import Product
from app.models.product_access import ProductAccess
from app.models.progress_summary import ProgressSummary
from app.models.referral_code import ReferralCode
from app.models.repository import Repository
from app.models.subscription import Subscription
from app.models.user import User
from app.models.work_item import WorkItem
from tests.helpers.tracker import ResourceTracker

logger = logging.getLogger(__name__)


class CleanupError(Exception):
    """Raised when one or more cleanup operations fail."""


class TestCleanup:
    """Handles cleanup of all test resources in FK-dependency order."""

    async def cleanup_all(
        self,
        tracker: ResourceTracker,
        db: AsyncSession,
    ) -> None:
        """Delete all tracked resources in safe order.

        Order: products → org_members → organizations → users (DB) → users (Supabase)

        Every phase runs regardless of earlier failures. If any phase fails,
        a single ``CleanupError`` is raised after all phases complete.
        """
        logger.info(f"Starting cleanup. {tracker.summary}")
        failures: list[str] = []

        # Phase 1: Standalone product children (not covered by product cascade)
        for repo_id in reversed(tracker.repositories):
            await self._delete_resource(db, Repository, repo_id, "Repository", failures)
        for doc_id in reversed(tracker.documents):
            await self._delete_resource(db, Document, doc_id, "Document", failures)
        for wi_id in reversed(tracker.work_items):
            await self._delete_resource(db, WorkItem, wi_id, "WorkItem", failures)
        for ai_id in reversed(tracker.app_info):
            await self._delete_resource(db, AppInfo, ai_id, "AppInfo", failures)

        # Phase 2: Products and children (reverse creation order)
        for product_id in reversed(tracker.products):
            await self._delete_product_cascade(db, product_id, failures)

        # Phase 3: User-scoped resources (before user deletion)
        for fb_id in reversed(tracker.feedback):
            await self._delete_resource(db, Feedback, fb_id, "Feedback", failures)
        for rc_id in reversed(tracker.referral_codes):
            await self._delete_resource(db, ReferralCode, rc_id, "ReferralCode", failures)

        # Phase 4: Organization memberships
        for org_id, user_id in tracker.org_members:
            await self._delete_org_member(db, org_id, user_id, failures)

        # Phase 5: Organizations (cascades subscription)
        for org_id in reversed(tracker.organizations):
            await self._delete_organization_cascade(db, org_id, failures)

        # Phase 6: Users from app database
        for user_id in reversed(tracker.users):
            await self._delete_user_app_db(db, user_id, failures)

        await db.commit()

        # Phase 7: Verify nothing leaked
        await self._verify_cleanup(tracker, db)

        # Phase 8: Users from Supabase Auth (after DB commit)
        for user_id in reversed(tracker.users):
            await self._delete_user_supabase(user_id, failures)

        if failures:
            msg = f"{len(failures)} cleanup operation(s) failed:\n" + "\n".join(
                f"  - {f}" for f in failures
            )
            logger.error(msg)
            raise CleanupError(msg)

        logger.info("Cleanup complete.")

    async def _delete_resource(
        self,
        db: AsyncSession,
        model: type,
        resource_id: UUID,
        label: str,
        failures: list[str],
    ) -> None:
        """Generic single-resource delete by ID."""
        try:
            await db.execute(delete(model).where(model.id == resource_id))
            logger.debug(f"Deleted {label}: {resource_id}")
        except Exception as exc:
            failures.append(f"{label} {resource_id}: {exc}")
            logger.exception(f"Failed to delete {label} {resource_id}")

    async def _delete_product_cascade(
        self, db: AsyncSession, product_id: UUID, failures: list[str]
    ) -> None:
        """Delete product and all child entities in FK-safe order."""
        try:
            # 1. Document (FK → DocumentSubsection, DocumentSection, Product)
            await db.execute(delete(Document).where(Document.product_id == product_id))

            # 2. DocumentSubsection (FK → DocumentSection)
            section_ids_subq = select(DocumentSection.id).where(
                DocumentSection.product_id == product_id
            )
            await db.execute(
                delete(DocumentSubsection).where(
                    DocumentSubsection.section_id.in_(section_ids_subq)
                )
            )

            # 3. DocumentSection (FK → Product)
            await db.execute(
                delete(DocumentSection).where(DocumentSection.product_id == product_id)
            )

            # 4. Other product children
            await db.execute(delete(Repository).where(Repository.product_id == product_id))
            await db.execute(delete(WorkItem).where(WorkItem.product_id == product_id))
            await db.execute(delete(ProductAccess).where(ProductAccess.product_id == product_id))
            await db.execute(delete(AppInfo).where(AppInfo.product_id == product_id))

            # 5. Cache/summary tables (FK → Product, RESTRICT)
            await db.execute(
                delete(DashboardShippedSummary).where(
                    DashboardShippedSummary.product_id == product_id
                )
            )
            await db.execute(
                delete(ProgressSummary).where(ProgressSummary.product_id == product_id)
            )
            await db.execute(delete(CustomDocJob).where(CustomDocJob.product_id == product_id))

            # 6. Product itself
            await db.execute(delete(Product).where(Product.id == product_id))
            logger.debug(f"Deleted product cascade: {product_id}")
        except Exception as exc:
            failures.append(f"Product {product_id}: {exc}")
            logger.exception(f"Failed to delete product {product_id}")

    async def _delete_org_member(
        self, db: AsyncSession, org_id: UUID, user_id: UUID, failures: list[str]
    ) -> None:
        try:
            await db.execute(
                delete(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_id == user_id,
                )
            )
        except Exception as exc:
            failures.append(f"OrgMember org={org_id} user={user_id}: {exc}")
            logger.exception(f"Failed to delete org member org={org_id} user={user_id}")

    async def _delete_organization_cascade(
        self, db: AsyncSession, org_id: UUID, failures: list[str]
    ) -> None:
        """Delete org, members, and subscription."""
        try:
            await db.execute(
                delete(OrganizationMember).where(OrganizationMember.organization_id == org_id)
            )
            await db.execute(delete(Subscription).where(Subscription.organization_id == org_id))
            await db.execute(delete(Organization).where(Organization.id == org_id))
            logger.debug(f"Deleted organization cascade: {org_id}")
        except Exception as exc:
            failures.append(f"Organization {org_id}: {exc}")
            logger.exception(f"Failed to delete organization {org_id}")

    async def _delete_user_app_db(
        self, db: AsyncSession, user_id: UUID, failures: list[str]
    ) -> None:
        try:
            await db.execute(delete(User).where(User.id == user_id))
            logger.debug(f"Deleted user from app DB: {user_id}")
        except Exception as exc:
            failures.append(f"User (app DB) {user_id}: {exc}")
            logger.exception(f"Failed to delete user {user_id} from app DB")

    async def _verify_cleanup(self, tracker: ResourceTracker, db: AsyncSession) -> None:
        """Check for leaked resources after cleanup and log warnings."""
        leaked = False

        checks: list[tuple[str, type, list]] = [
            ("Product", Product, tracker.products),
            ("Organization", Organization, tracker.organizations),
            ("User", User, tracker.users),
            ("Repository", Repository, tracker.repositories),
            ("Document", Document, tracker.documents),
            ("WorkItem", WorkItem, tracker.work_items),
            ("AppInfo", AppInfo, tracker.app_info),
            ("Feedback", Feedback, tracker.feedback),
            ("ReferralCode", ReferralCode, tracker.referral_codes),
        ]

        for label, model, ids in checks:
            for resource_id in ids:
                result = await db.execute(select(model).where(model.id == resource_id))
                if result.scalar_one_or_none():
                    logger.warning(f"CLEANUP LEAK: {label} {resource_id} still exists")
                    leaked = True

        if not leaked:
            logger.debug("Cleanup verification passed — no leaked resources")

    async def _delete_user_supabase(self, user_id: UUID, failures: list[str]) -> None:
        """Delete user from Supabase Auth via Admin API."""
        try:
            from supabase import create_client

            from app.config.settings import settings

            client = create_client(settings.supabase_url, settings.supabase_service_role_key)
            client.auth.admin.delete_user(str(user_id))
            logger.debug(f"Deleted user from Supabase Auth: {user_id}")
        except Exception as exc:
            failures.append(f"User (Supabase) {user_id}: {exc}")
            logger.exception(f"Failed to delete user {user_id} from Supabase Auth")
