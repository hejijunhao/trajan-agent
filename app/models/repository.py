import uuid as uuid_pkg
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.product import Product


class RepositoryBase(SQLModel):
    """Base fields for Repository."""

    name: str | None = Field(default=None, max_length=255, index=True)
    full_name: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    url: str | None = Field(default=None, max_length=500)
    default_branch: str | None = Field(default=None, max_length=100)
    is_private: bool | None = Field(default=False)
    language: str | None = Field(default=None, max_length=50)

    # GitHub metadata (stored at import time)
    github_id: int | None = Field(default=None, index=True)
    stars_count: int | None = Field(default=None)
    forks_count: int | None = Field(default=None)


class RepositoryCreate(SQLModel):
    """Schema for creating a repository."""

    product_id: uuid_pkg.UUID
    name: str
    full_name: str | None = None
    description: str | None = None
    url: str | None = None
    default_branch: str | None = None
    is_private: bool = False
    language: str | None = None
    github_id: int | None = None


class RepositoryUpdate(SQLModel):
    """Schema for updating a repository."""

    name: str | None = None
    description: str | None = None
    url: str | None = None
    default_branch: str | None = None


class Repository(RepositoryBase, UUIDMixin, TimestampMixin, UserOwnedMixin, table=True):
    """Repository linked to a Product."""

    __tablename__ = "repositories"

    product_id: uuid_pkg.UUID | None = Field(
        default=None,
        foreign_key="products.id",
        index=True,
    )

    # Relationships
    product: Optional["Product"] = Relationship(back_populates="repositories")
