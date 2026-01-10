import uuid as uuid_pkg
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.product import Product


class WorkItemBase(SQLModel):
    """Base fields for WorkItem."""

    title: str | None = Field(default=None, max_length=500, index=True)
    description: str | None = Field(default=None)
    type: str | None = Field(default=None, max_length=50)  # e.g. feature, fix, refactor, investigation
    status: str | None = Field(default=None, max_length=50, index=True)  # e.g. todo, in_progress, done
    priority: int | None = Field(default=None)


class WorkItemCreate(SQLModel):
    """Schema for creating a work item."""

    product_id: uuid_pkg.UUID
    title: str
    description: str | None = None
    type: str | None = None
    status: str | None = None
    priority: int | None = None
    repository_id: uuid_pkg.UUID | None = None


class WorkItemUpdate(SQLModel):
    """Schema for updating a work item."""

    title: str | None = None
    description: str | None = None
    type: str | None = None
    status: str | None = None
    priority: int | None = None


class WorkItem(WorkItemBase, UUIDMixin, TimestampMixin, UserOwnedMixin, table=True):
    """Work item (task, feature, fix, investigation) within a Product."""

    __tablename__ = "work_items"

    product_id: uuid_pkg.UUID | None = Field(
        default=None,
        foreign_key="products.id",
        index=True,
    )

    repository_id: uuid_pkg.UUID | None = Field(
        default=None,
        foreign_key="repositories.id",
        index=True,
    )

    # Relationships
    product: Optional["Product"] = Relationship(back_populates="work_items")
