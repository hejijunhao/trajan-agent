import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import generate_quick_access_token
from app.domain.base_operations import BaseOperations
from app.models.product import Product


class ProductOperations(BaseOperations[Product]):
    """CRUD operations for Product model."""

    def __init__(self) -> None:
        super().__init__(Product)

    async def get_by_quick_access_token(
        self,
        db: AsyncSession,
        token: str,
    ) -> Product | None:
        """Get a product by its quick access token (if enabled)."""
        statement = select(Product).where(
            Product.quick_access_token == token,  # type: ignore[arg-type]
            Product.quick_access_enabled == True,  # type: ignore[arg-type]  # noqa: E712
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def enable_quick_access(
        self,
        db: AsyncSession,
        product: Product,
        user_id: uuid_pkg.UUID,
    ) -> Product:
        """Enable quick access for a product, generating a new token if needed."""
        if not product.quick_access_token:
            product.quick_access_token = generate_quick_access_token()
        product.quick_access_enabled = True
        product.quick_access_created_at = datetime.now(UTC)
        product.quick_access_created_by = user_id
        db.add(product)
        await db.flush()
        await db.refresh(product)
        return product

    async def disable_quick_access(
        self,
        db: AsyncSession,
        product: Product,
    ) -> Product:
        """Disable quick access for a product (keeps token for re-enabling)."""
        product.quick_access_enabled = False
        db.add(product)
        await db.flush()
        await db.refresh(product)
        return product

    async def regenerate_quick_access_token(
        self,
        db: AsyncSession,
        product: Product,
        user_id: uuid_pkg.UUID,
    ) -> Product:
        """Generate a new quick access token (invalidates old links)."""
        product.quick_access_token = generate_quick_access_token()
        product.quick_access_created_at = datetime.now(UTC)
        product.quick_access_created_by = user_id
        db.add(product)
        await db.flush()
        await db.refresh(product)
        return product

    async def get_with_relations(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        id: uuid_pkg.UUID,
    ) -> Product | None:
        """Get product with all related entities."""
        statement = (
            select(Product)
            .where(Product.id == id, Product.user_id == user_id)  # type: ignore[arg-type]
            .options(
                selectinload(Product.repositories),  # type: ignore[arg-type]
                selectinload(Product.work_items),  # type: ignore[arg-type]
                selectinload(Product.documents),  # type: ignore[arg-type]
                selectinload(Product.app_info_entries),  # type: ignore[arg-type]
            )
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        name: str,
    ) -> Product | None:
        """Find a product by name for a user."""
        statement = select(Product).where(
            Product.user_id == user_id,  # type: ignore[arg-type]
            Product.name == name,  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()


product_ops = ProductOperations()
