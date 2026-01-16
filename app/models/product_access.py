"""Product access model - per-user, project-scoped access control."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.user import User


class ProductAccessLevel(str, Enum):
    """Access levels for product collaborators."""

    ADMIN = "admin"  # Full access, can manage collaborators
    EDITOR = "editor"  # Read + write, can access Variables tab
    VIEWER = "viewer"  # Read-only, NO Variables tab access
    NONE = "none"  # Explicitly revoked access


class ProductAccess(SQLModel, table=True):
    """
    Product access - per-user access control for products.

    Tracks which users have explicit access to which products and at what level.
    Org owners/admins automatically have admin access to all products.
    Members/viewers must be explicitly added.
    """

    __tablename__ = "product_access"
    __table_args__ = (
        UniqueConstraint("product_id", "user_id", name="uq_product_access_product_user"),
    )

    id: uuid_pkg.UUID = Field(
        default_factory=uuid_pkg.uuid4,
        primary_key=True,
        nullable=False,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )
    product_id: uuid_pkg.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    user_id: uuid_pkg.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    access_level: str = Field(
        default=ProductAccessLevel.VIEWER.value,
        sa_column=Column(String(20), nullable=False, server_default="viewer"),
    )

    # Timestamps
    created_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
    )
    updated_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
    )

    # Relationships
    product: Optional["Product"] = Relationship(back_populates="access_entries")
    user: Optional["User"] = Relationship(back_populates="product_access_entries")


# Request/Response schemas
class ProductAccessCreate(SQLModel):
    """Schema for granting product access."""

    user_id: uuid_pkg.UUID
    access_level: str = ProductAccessLevel.VIEWER.value


class ProductAccessUpdate(SQLModel):
    """Schema for updating access level."""

    access_level: str


class ProductAccessRead(SQLModel):
    """Schema for reading product access."""

    id: uuid_pkg.UUID
    product_id: uuid_pkg.UUID
    user_id: uuid_pkg.UUID
    access_level: str
    created_at: datetime
    updated_at: datetime
