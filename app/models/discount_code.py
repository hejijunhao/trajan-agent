"""Discount code models — codes and redemption audit trail."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class DiscountCode(UUIDMixin, TimestampMixin, SQLModel, table=True):
    """
    Platform-managed discount codes.

    Created by platform admins directly in the DB. Org owners/admins
    redeem codes from billing settings to get a recurring % off via Stripe.
    """

    __tablename__ = "discount_codes"
    __table_args__ = (Index("ix_discount_codes_code", "code", unique=True),)

    code: str = Field(
        sa_column=Column(String(50), nullable=False, unique=True, index=True),
    )
    description: str | None = Field(default=None, max_length=500, nullable=True)
    discount_percent: int = Field(nullable=False)
    max_redemptions: int | None = Field(default=None, nullable=True)
    times_redeemed: int = Field(default=0, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    stripe_coupon_id: str | None = Field(default=None, max_length=255, nullable=True)


class DiscountRedemption(UUIDMixin, SQLModel, table=True):
    """
    Audit trail for discount code redemptions.

    One record per org that redeems a code.
    """

    __tablename__ = "discount_redemptions"
    __table_args__ = (
        Index("ix_discount_redemptions_org", "organization_id"),
        Index("ix_discount_redemptions_code", "discount_code_id"),
    )

    discount_code_id: uuid_pkg.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("discount_codes.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    organization_id: uuid_pkg.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    redeemed_by: uuid_pkg.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    redeemed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
    )

    # Relationships
    discount_code: Optional["DiscountCode"] = Relationship()
    organization: Optional["Organization"] = Relationship()
    user: Optional["User"] = Relationship()
