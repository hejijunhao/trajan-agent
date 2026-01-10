"""
One-time data migration: Create personal organizations for existing users.

This script should be run AFTER the Alembic migration that creates the
organizations and organization_members tables.

Usage:
    cd backend
    source .venv/bin/activate
    python -m app.tasks.migrate_users_to_orgs

What it does:
1. For each existing user, creates a personal organization
2. Adds the user as OWNER of their organization
3. Updates all their products to belong to the new organization

This is idempotent - running it multiple times won't create duplicate orgs.
"""

import asyncio
import logging
import sys

from sqlalchemy import select, update

from app.core.database import async_session_maker
from app.domain.organization_operations import organization_ops
from app.models.product import Product
from app.models.user import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def migrate_users_to_organizations() -> None:
    """
    Create personal organizations for all existing users and migrate their products.

    This is idempotent - users who already have an organization are skipped.
    """
    logger.info("Starting user-to-organization migration...")

    async with async_session_maker() as db:
        # Get all users
        result = await db.execute(select(User))
        users = list(result.scalars().all())
        logger.info(f"Found {len(users)} users to process")

        migrated_count = 0
        skipped_count = 0
        product_count = 0

        for user in users:
            # Check if user already has an organization
            existing_orgs = await organization_ops.get_for_user(db, user.id)
            if existing_orgs:
                logger.debug(f"User {user.email} already has {len(existing_orgs)} org(s), skipping")
                skipped_count += 1
                continue

            # Create personal organization
            org = await organization_ops.create_personal_org(
                db,
                user_id=user.id,
                user_name=user.display_name,
                user_email=user.email,
            )
            logger.info(f"Created organization '{org.name}' (slug: {org.slug}) for user {user.email}")

            # Move user's products to the new organization
            update_stmt = (
                update(Product)
                .where(Product.user_id == user.id)
                .where(Product.organization_id.is_(None))
                .values(organization_id=org.id)
            )
            result = await db.execute(update_stmt)
            products_moved = result.rowcount
            product_count += products_moved

            if products_moved > 0:
                logger.info(f"  Moved {products_moved} product(s) to organization")

            migrated_count += 1

        await db.commit()

        logger.info("=" * 60)
        logger.info("Migration complete!")
        logger.info(f"  Users migrated: {migrated_count}")
        logger.info(f"  Users skipped (already had org): {skipped_count}")
        logger.info(f"  Products moved: {product_count}")
        logger.info("=" * 60)


async def verify_migration() -> None:
    """Verify the migration was successful by checking data integrity."""
    logger.info("Verifying migration...")

    async with async_session_maker() as db:
        # Count users without organizations
        result = await db.execute(select(User))
        users = list(result.scalars().all())

        users_without_org = 0
        for user in users:
            orgs = await organization_ops.get_for_user(db, user.id)
            if not orgs:
                users_without_org += 1
                logger.warning(f"User {user.email} has no organization!")

        # Count products without organization_id
        result = await db.execute(
            select(Product).where(Product.organization_id.is_(None))
        )
        orphan_products = list(result.scalars().all())

        logger.info("=" * 60)
        logger.info("Verification results:")
        logger.info(f"  Users without organization: {users_without_org}")
        logger.info(f"  Products without organization: {len(orphan_products)}")

        if users_without_org == 0 and len(orphan_products) == 0:
            logger.info("  Status: PASS - All data migrated successfully")
        else:
            logger.warning("  Status: INCOMPLETE - Some data needs attention")

        logger.info("=" * 60)


def main() -> None:
    """Run the migration."""
    if len(sys.argv) > 1 and sys.argv[1] == "--verify":
        asyncio.run(verify_migration())
    else:
        asyncio.run(migrate_users_to_organizations())


if __name__ == "__main__":
    main()
