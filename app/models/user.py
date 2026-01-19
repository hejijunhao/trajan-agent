import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.organization import Organization, OrganizationMember
    from app.models.product import Product
    from app.models.product_access import ProductAccess
    from app.models.user_preferences import UserPreferences


class User(SQLModel, table=True):
    """
    User model - mirrors Supabase auth.users.

    The id comes from Supabase Auth. User records are created
    on first API call after OAuth authentication.
    """

    __tablename__ = "users"

    id: uuid_pkg.UUID = Field(
        primary_key=True,
        index=True,
        nullable=False,
        description="UUID from Supabase auth.users",
    )
    email: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=100)
    github_username: str | None = Field(default=None, max_length=255, index=True)
    avatar_url: str | None = Field(default=None, max_length=500)
    auth_provider: str | None = Field(default=None, max_length=50)

    # Admin flag - for manual plan assignment, bypassing Stripe
    is_admin: bool = Field(
        default=False,
        nullable=False,
        sa_column_kwargs={"comment": "Admin flag for manual plan assignment and admin operations"},
    )

    # Onboarding state
    onboarding_completed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        description="Timestamp when user completed onboarding wizard",
    )

    created_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
    )
    updated_at: datetime | None = Field(  # type: ignore[call-overload]
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": text("now()")},
    )

    # Relationships
    products: list["Product"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"foreign_keys": "[Product.user_id]"},
    )
    preferences: Optional["UserPreferences"] = Relationship(back_populates="user")

    # Organization relationships
    owned_organizations: list["Organization"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"foreign_keys": "[Organization.owner_id]"},
    )
    organization_memberships: list["OrganizationMember"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"foreign_keys": "[OrganizationMember.user_id]"},
    )

    # Product access relationships
    product_access_entries: list["ProductAccess"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"foreign_keys": "[ProductAccess.user_id]"},
    )
