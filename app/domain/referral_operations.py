"""Domain operations for referral codes."""

import random
import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.base_operations import BaseOperations
from app.models.referral_code import ReferralCode
from app.models.user import User


def generate_referral_code(display_name: str | None, email: str | None) -> str:
    """
    Generate a referral code in format: NAME-XXXX

    Examples:
    - "SARAH-X7K9" (from display_name "Sarah")
    - "TRAJAN-A3B2" (fallback when no name)

    Uses first name (up to 6 chars), uppercase, alphanumeric only.
    """
    # Extract base from display name or email
    if display_name:
        # Take first word (first name) and clean it
        base = display_name.split()[0].upper()[:6]
        base = "".join(c for c in base if c.isalnum())
    elif email:
        # Take part before @ and clean it
        base = email.split("@")[0].upper()[:6]
        base = "".join(c for c in base if c.isalnum())
    else:
        base = "TRAJAN"

    # Fallback if base is too short
    if len(base) < 2:
        base = "TRAJAN"

    # Generate random suffix (4 alphanumeric chars, no confusing chars)
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # No I, O, 0, 1 (confusing)
    suffix = "".join(random.choice(chars) for _ in range(4))

    return f"{base}-{suffix}"


class ReferralOperations(BaseOperations[ReferralCode]):
    """CRUD operations for ReferralCode model."""

    def __init__(self) -> None:
        super().__init__(ReferralCode)

    async def get_user_codes(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ReferralCode]:
        """Get all referral codes for a user, ordered by creation date (newest first)."""
        statement = (
            select(ReferralCode)
            .where(ReferralCode.user_id == user_id)  # type: ignore[arg-type]
            .options(selectinload(ReferralCode.redeemed_by))  # type: ignore[arg-type]
            .offset(skip)
            .limit(limit)
            .order_by(ReferralCode.created_at.desc())  # type: ignore[attr-defined]
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_user_code_count(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> int:
        """Count how many referral codes a user has created."""
        statement = (
            select(func.count())
            .select_from(ReferralCode)
            .where(ReferralCode.user_id == user_id)  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        count = result.scalar()
        return int(count) if count else 0

    async def get_remaining_invites(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> int:
        """
        Calculate remaining invites: user.invite_limit - COUNT(existing codes).

        Returns 0 if user not found or no invites remaining.
        """
        # Get user to check invite limit
        user_stmt = select(User).where(User.id == user_id)  # type: ignore[arg-type]
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if user is None:
            return 0

        # Count existing codes
        code_count = await self.get_user_code_count(db, user_id)

        return max(0, user.invite_limit - code_count)

    async def create_code(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> ReferralCode:
        """
        Generate a new referral code for a user.

        Raises ValueError if user has no remaining invites.
        Ensures generated code is unique (retries on collision).
        """
        # Check remaining invites
        remaining = await self.get_remaining_invites(db, user_id)
        if remaining <= 0:
            raise ValueError("No remaining referral invites available")

        # Get user info for code generation
        user_stmt = select(User).where(User.id == user_id)  # type: ignore[arg-type]
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if not user:
            raise ValueError("User not found")

        # Generate unique code (retry up to 5 times on collision)
        for _ in range(5):
            code = generate_referral_code(user.display_name, user.email)

            # Check if code already exists
            existing = await self.get_by_code(db, code)
            if not existing:
                break
        else:
            # Extremely unlikely - fall back to UUID-based code
            code = f"REF-{uuid_pkg.uuid4().hex[:8].upper()}"

        # Create the referral code
        referral = ReferralCode(
            user_id=user_id,
            code=code,
        )
        db.add(referral)
        await db.flush()
        await db.refresh(referral)
        return referral

    async def get_by_code(
        self,
        db: AsyncSession,
        code: str,
    ) -> ReferralCode | None:
        """Get a referral code by its code string."""
        statement = (
            select(ReferralCode)
            .where(ReferralCode.code == code.upper())  # type: ignore[arg-type]
            .options(selectinload(ReferralCode.owner))  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def validate_code(
        self,
        db: AsyncSession,
        code: str,
    ) -> ReferralCode | None:
        """
        Validate a referral code exists and is available for redemption.

        Returns the code if valid and unredeemed, None otherwise.
        """
        referral = await self.get_by_code(db, code)
        if referral and referral.is_available:
            return referral
        return None

    async def redeem_code(
        self,
        db: AsyncSession,
        code: str,
        recipient_user_id: uuid_pkg.UUID,
    ) -> ReferralCode:
        """
        Mark a referral code as redeemed by a new user.

        Called during/after sign-up when a user registers with a referral code.
        Validates that:
        - Code exists and is available
        - Recipient is not the code owner (self-referral)
        - Recipient hasn't already used a referral code

        Raises ValueError on validation failure.
        """
        referral = await self.get_by_code(db, code)

        if not referral:
            raise ValueError(f"Invalid referral code: {code}")

        if not referral.is_available:
            raise ValueError(f"Referral code already used: {code}")

        if referral.user_id == recipient_user_id:
            raise ValueError("Cannot redeem your own referral code")

        # Check if recipient has already redeemed a different code
        existing_stmt = select(ReferralCode).where(
            ReferralCode.redeemed_by_user_id == recipient_user_id  # type: ignore[arg-type]
        )
        existing_result = await db.execute(existing_stmt)
        if existing_result.scalar_one_or_none():
            raise ValueError("User has already redeemed a referral code")

        # Mark as redeemed
        referral.redeemed_at = datetime.now(UTC)
        referral.redeemed_by_user_id = recipient_user_id
        db.add(referral)
        await db.flush()
        await db.refresh(referral)
        return referral

    async def get_pending_referral_for_recipient(
        self,
        db: AsyncSession,
        recipient_user_id: uuid_pkg.UUID,
    ) -> ReferralCode | None:
        """
        Get a pending (redeemed but not converted) referral for a recipient user.

        Used during checkout completion to check if user signed up via referral.
        """
        statement = (
            select(ReferralCode)
            .where(
                ReferralCode.redeemed_by_user_id == recipient_user_id,  # type: ignore[arg-type]
                ReferralCode.converted_at.is_(None),  # type: ignore[union-attr]
            )
            .options(selectinload(ReferralCode.owner))  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def mark_converted(
        self,
        db: AsyncSession,
        recipient_user_id: uuid_pkg.UUID,
    ) -> ReferralCode | None:
        """
        Mark referral as converted when recipient adds payment.

        Called when recipient completes payment setup (Stripe subscription created).
        This triggers the sender reward (1 free month).

        Returns the converted referral code, or None if recipient has no pending referral.
        """
        # Find the referral code redeemed by this user
        statement = select(ReferralCode).where(
            ReferralCode.redeemed_by_user_id == recipient_user_id,  # type: ignore[arg-type]
            ReferralCode.converted_at.is_(None),  # type: ignore[union-attr]
        )
        result = await db.execute(statement)
        referral = result.scalar_one_or_none()

        if not referral:
            return None

        # Mark as converted
        referral.converted_at = datetime.now(UTC)
        db.add(referral)
        await db.flush()
        await db.refresh(referral)
        return referral

    async def get_referral_stats(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> dict[str, Any]:
        """
        Get referral statistics for a user.

        Returns dict with:
        - total_codes: Number of codes created
        - available: Number of unredeemed codes
        - pending: Number of redeemed but not converted
        - converted: Number of fully converted referrals
        - remaining_invites: How many more codes can be created
        """
        codes = await self.get_user_codes(db, user_id)
        remaining = await self.get_remaining_invites(db, user_id)

        # Get invite limit
        user_stmt = select(User).where(User.id == user_id)  # type: ignore[arg-type]
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        invite_limit = user.invite_limit if user else 3

        return {
            "total_codes": len(codes),
            "available": sum(1 for c in codes if c.is_available),
            "pending": sum(1 for c in codes if c.is_pending),
            "converted": sum(1 for c in codes if c.is_converted),
            "remaining_invites": remaining,
            "invite_limit": invite_limit,
        }


# Singleton instance
referral_ops = ReferralOperations()
