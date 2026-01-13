"""Organization model - billing and team unit."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Column, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.subscription import Subscription
    from app.models.user import User


class Organization(SQLModel, table=True):
    """
    Organization model - the billing and team unit.

    Organizations own products and have subscriptions. Each user gets a
    personal organization on signup. Users can belong to multiple organizations.
    """

    __tablename__ = "organizations"

    id: uuid_pkg.UUID = Field(
        default_factory=uuid_pkg.uuid4,
        primary_key=True,
        nullable=False,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )
    name: str = Field(max_length=100, nullable=False)
    slug: str = Field(max_length=100, unique=True, index=True, nullable=False)

    # Ownership - primary billing contact
    owner_id: uuid_pkg.UUID = Field(foreign_key="users.id", nullable=False, index=True)

    # Settings (extensible)
    settings: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_column_kwargs={"server_default": text("now()")},
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column_kwargs={"onupdate": text("now()")},
    )

    # Relationships
    owner: Optional["User"] = Relationship(
        back_populates="owned_organizations",
        sa_relationship_kwargs={"foreign_keys": "[Organization.owner_id]"},
    )
    members: list["OrganizationMember"] = Relationship(
        back_populates="organization",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    products: list["Product"] = Relationship(back_populates="organization")
    subscription: Optional["Subscription"] = Relationship(
        back_populates="organization",
        sa_relationship_kwargs={"uselist": False, "cascade": "all, delete-orphan"},
    )


class MemberRole(str, Enum):
    """Role levels for organization members."""

    OWNER = "owner"  # Full access, billing control, can delete org
    ADMIN = "admin"  # Full access, no billing control
    MEMBER = "member"  # Standard access
    VIEWER = "viewer"  # Read-only (future)


class OrganizationMember(SQLModel, table=True):
    """
    Organization membership - join table between users and organizations.

    Tracks which users belong to which organizations and their role.
    """

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
    )

    id: uuid_pkg.UUID = Field(
        default_factory=uuid_pkg.uuid4,
        primary_key=True,
        nullable=False,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )
    organization_id: uuid_pkg.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
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
    role: str = Field(
        default=MemberRole.MEMBER.value,
        sa_column=Column(String(20), nullable=False, server_default="member"),
    )

    # Invitation tracking
    invited_by: uuid_pkg.UUID | None = Field(
        foreign_key="users.id", default=None, nullable=True
    )
    invited_at: datetime | None = Field(default=None, nullable=True)
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_column_kwargs={"server_default": text("now()")},
    )

    # Relationships
    organization: Optional["Organization"] = Relationship(back_populates="members")
    user: Optional["User"] = Relationship(
        back_populates="organization_memberships",
        sa_relationship_kwargs={"foreign_keys": "[OrganizationMember.user_id]"},
    )


# Request/Response schemas
class OrganizationCreate(SQLModel):
    """Schema for creating an organization."""

    name: str
    slug: str | None = None  # Auto-generated if not provided


class OrganizationUpdate(SQLModel):
    """Schema for updating an organization."""

    name: str | None = None
    slug: str | None = None


class OrganizationMemberCreate(SQLModel):
    """Schema for adding a member to an organization."""

    email: str
    role: str = MemberRole.MEMBER.value


class OrganizationMemberUpdate(SQLModel):
    """Schema for updating a member's role."""

    role: str
