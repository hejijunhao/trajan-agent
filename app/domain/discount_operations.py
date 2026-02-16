"""Domain operations for discount codes."""

import uuid as uuid_pkg

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.base_operations import BaseOperations
from app.models.discount_code import DiscountCode, DiscountRedemption


class DiscountOperations(BaseOperations[DiscountCode]):
    """CRUD operations for DiscountCode model."""

    def __init__(self) -> None:
        super().__init__(DiscountCode)

    async def validate_code(
        self,
        db: AsyncSession,
        code: str,
    ) -> DiscountCode:
        """
        Validate a discount code exists and is redeemable.

        Returns the DiscountCode if valid.
        Raises ValueError if code is invalid, inactive, or exhausted.
        """
        statement = select(DiscountCode).where(
            DiscountCode.code == code.upper(),  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        discount = result.scalar_one_or_none()

        if not discount:
            raise ValueError(f"Invalid discount code: {code}")

        if not discount.is_active:
            raise ValueError(f"Discount code is no longer active: {code}")

        if (
            discount.max_redemptions is not None
            and discount.times_redeemed >= discount.max_redemptions
        ):
            raise ValueError(f"Discount code has reached its redemption limit: {code}")

        return discount

    async def redeem_code(
        self,
        db: AsyncSession,
        code: str,
        organization_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> DiscountRedemption:
        """
        Record a discount code redemption for an organization.

        Validates the code, checks for existing redemptions, creates
        a redemption record, and increments the counter.

        Raises ValueError on validation failure.
        """
        discount = await self.validate_code(db, code)

        # Check if org already has an active redemption
        existing = await self.get_active_discount_for_org(db, organization_id)
        if existing:
            raise ValueError("Organization already has an active discount")

        # Create redemption record
        redemption = DiscountRedemption(
            discount_code_id=discount.id,
            organization_id=organization_id,
            redeemed_by=user_id,
        )
        db.add(redemption)

        # Increment counter
        discount.times_redeemed += 1
        db.add(discount)

        await db.flush()
        await db.refresh(redemption)
        return redemption

    async def get_active_discount_for_org(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
    ) -> DiscountRedemption | None:
        """
        Get the current active discount redemption for an organization.

        Returns the redemption with its associated discount code, or None.
        """
        statement = (
            select(DiscountRedemption)
            .where(
                DiscountRedemption.organization_id == organization_id,  # type: ignore[arg-type]
            )
            .options(
                selectinload(DiscountRedemption.discount_code),  # type: ignore[arg-type]
            )
            .order_by(DiscountRedemption.redeemed_at.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def remove_discount_for_org(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
    ) -> bool:
        """
        Remove the active discount for an organization by deleting the redemption.

        Returns True if a redemption was removed, False if none existed.
        """
        redemption = await self.get_active_discount_for_org(db, organization_id)
        if not redemption:
            return False

        await db.delete(redemption)
        await db.flush()
        return True


# Singleton instance
discount_ops = DiscountOperations()
