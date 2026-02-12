"""Emergency cleanup script — delete ALL test data from production.

Run manually if test cleanup fails and test data leaks into production.

Usage:
    cd backend && python -m scripts.cleanup_test_data

This script:
1. Finds all users matching the test email pattern
2. Deletes their orgs, products, and all child entities
3. Deletes the users from the app DB
4. Deletes the users from Supabase Auth
"""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Test email pattern — matches all integration test users
TEST_EMAIL_PATTERN = "test-%@trajan-integration-test.local"
# Also catch unit test data
UNIT_TEST_EMAIL_PATTERN = "__test_%@example.com"


async def emergency_cleanup() -> None:
    """Delete ALL test data from production."""
    from app.config.settings import settings
    from app.models.app_info import AppInfo
    from app.models.custom_doc_job import CustomDocJob
    from app.models.dashboard_shipped_summary import DashboardShippedSummary
    from app.models.document import Document
    from app.models.document_section import DocumentSection, DocumentSubsection
    from app.models.organization import Organization, OrganizationMember
    from app.models.product import Product
    from app.models.product_access import ProductAccess
    from app.models.progress_summary import ProgressSummary
    from app.models.repository import Repository
    from app.models.subscription import Subscription
    from app.models.user import User
    from app.models.work_item import WorkItem

    engine = create_async_engine(settings.database_url_direct, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Find test users
        result = await db.execute(
            select(User).where(
                User.email.like(TEST_EMAIL_PATTERN)  # type: ignore[union-attr]
                | User.email.like(UNIT_TEST_EMAIL_PATTERN)  # type: ignore[union-attr]
            )
        )
        test_users = result.scalars().all()

        if not test_users:
            logger.info("No test data found. Database is clean.")
            return

        logger.info(f"Found {len(test_users)} test users to clean up:")
        for u in test_users:
            logger.info(f"  - {u.email} ({u.id})")

        # Confirm
        if "--yes" not in sys.argv:
            confirm = input(f"\nDelete {len(test_users)} test users and all their data? [y/N] ")
            if confirm.lower() != "y":
                logger.info("Aborted.")
                return

        user_ids = [u.id for u in test_users]

        # Find orgs owned by test users
        org_result = await db.execute(
            select(Organization).where(Organization.owner_id.in_(user_ids))
        )
        test_orgs = org_result.scalars().all()
        org_ids = [o.id for o in test_orgs]

        # Find products in those orgs
        if org_ids:
            product_result = await db.execute(
                select(Product).where(Product.organization_id.in_(org_ids))
            )
            test_products = product_result.scalars().all()
            product_ids = [p.id for p in test_products]

            # Delete product children in FK-safe order
            if product_ids:
                # 1. Document (FK → DocumentSubsection, DocumentSection, Product)
                await db.execute(
                    Document.__table__.delete().where(Document.product_id.in_(product_ids))
                )

                # 2. DocumentSubsection (FK → DocumentSection)
                section_ids_subq = select(DocumentSection.id).where(
                    DocumentSection.product_id.in_(product_ids)
                )
                await db.execute(
                    DocumentSubsection.__table__.delete().where(
                        DocumentSubsection.section_id.in_(section_ids_subq)
                    )
                )

                # 3. DocumentSection (FK → Product)
                await db.execute(
                    DocumentSection.__table__.delete().where(
                        DocumentSection.product_id.in_(product_ids)
                    )
                )

                # 4. Other product children
                await db.execute(
                    Repository.__table__.delete().where(Repository.product_id.in_(product_ids))
                )
                await db.execute(
                    WorkItem.__table__.delete().where(WorkItem.product_id.in_(product_ids))
                )
                await db.execute(
                    ProductAccess.__table__.delete().where(
                        ProductAccess.product_id.in_(product_ids)
                    )
                )
                await db.execute(
                    AppInfo.__table__.delete().where(AppInfo.product_id.in_(product_ids))
                )

                # 5. Cache/summary tables (FK → Product, RESTRICT)
                await db.execute(
                    DashboardShippedSummary.__table__.delete().where(
                        DashboardShippedSummary.product_id.in_(product_ids)
                    )
                )
                await db.execute(
                    ProgressSummary.__table__.delete().where(
                        ProgressSummary.product_id.in_(product_ids)
                    )
                )
                await db.execute(
                    CustomDocJob.__table__.delete().where(
                        CustomDocJob.product_id.in_(product_ids)
                    )
                )

                # 6. Products themselves
                await db.execute(Product.__table__.delete().where(Product.id.in_(product_ids)))
                logger.info(f"Deleted {len(product_ids)} products and children")

            # Delete org children
            await db.execute(
                OrganizationMember.__table__.delete().where(
                    OrganizationMember.organization_id.in_(org_ids)
                )
            )
            await db.execute(
                Subscription.__table__.delete().where(Subscription.organization_id.in_(org_ids))
            )
            await db.execute(Organization.__table__.delete().where(Organization.id.in_(org_ids)))
            logger.info(f"Deleted {len(org_ids)} organizations")

        # Delete org memberships where test users are members (not owners)
        await db.execute(
            OrganizationMember.__table__.delete().where(OrganizationMember.user_id.in_(user_ids))
        )

        # Delete users
        await db.execute(User.__table__.delete().where(User.id.in_(user_ids)))
        logger.info(f"Deleted {len(user_ids)} users from app DB")

        await db.commit()

    # Delete from Supabase Auth
    try:
        from supabase import create_client

        client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        for user in test_users:
            try:
                client.auth.admin.delete_user(str(user.id))
                logger.info(f"Deleted from Supabase Auth: {user.email}")
            except Exception as e:
                logger.warning(f"Failed to delete {user.email} from Supabase: {e}")
    except ImportError:
        logger.warning("supabase package not available — skipping Supabase Auth cleanup")

    await engine.dispose()
    logger.info("Emergency cleanup complete.")


if __name__ == "__main__":
    asyncio.run(emergency_cleanup())
