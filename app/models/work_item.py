import uuid as uuid_pkg
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.product import Product


class WorkItemBase(SQLModel):
    """Base fields for WorkItem."""

    title: str | None = Field(default=None, max_length=500, index=True)
    description: str | None = Field(default=None)
    type: str | None = Field(
        default=None, max_length=50
    )  # e.g. feature, fix, refactor, investigation
    status: str | None = Field(
        default=None, max_length=50, index=True
    )  # e.g. todo, in_progress, done
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
    plans: list[dict] | None = None
    tags: list[str] | None = None


class WorkItemUpdate(SQLModel):
    """Schema for updating a work item."""

    title: str | None = None
    description: str | None = None
    type: str | None = None
    status: str | None = None
    priority: int | None = None
    completed_at: datetime | None = None
    commit_sha: str | None = None
    commit_url: str | None = None
    plans: list[dict] | None = None
    tags: list[str] | None = None
    deleted_at: datetime | None = None


class WorkItemComplete(SQLModel):
    """Schema for completing a work item with a commit link."""

    commit_sha: str = Field(min_length=7, max_length=40)
    commit_url: str | None = None


class WorkItem(WorkItemBase, UUIDMixin, TimestampMixin, table=True):
    """Work item (task, feature, fix, investigation) within a Product.

    Visibility is controlled by Product access (RLS), not by user ownership.
    The created_by_user_id tracks who created the work item (for audit trail).
    """

    __tablename__ = "work_items"

    # Tracks who created this work item (for audit trail)
    # This does NOT control visibility - Product access does that via RLS
    created_by_user_id: uuid_pkg.UUID = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
    )

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

    # Feedback ticket fields
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    commit_sha: str | None = Field(default=None, max_length=40)
    commit_url: str | None = Field(default=None)
    plans: list[dict] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    tags: list[str] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    deleted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # Relationships
    product: Optional["Product"] = Relationship(back_populates="work_items")
