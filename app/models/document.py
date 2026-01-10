import uuid as uuid_pkg
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.product import Product


class DocumentBase(SQLModel):
    """Base fields for Document."""

    title: str | None = Field(default=None, max_length=500, index=True)
    content: str | None = Field(default=None)
    type: str | None = Field(default=None, max_length=50)  # e.g. blueprint, architecture, note, plan, changelog
    is_pinned: bool | None = Field(default=False)


class DocumentCreate(SQLModel):
    """Schema for creating a document."""

    product_id: uuid_pkg.UUID
    title: str
    content: str | None = None
    type: str | None = None
    is_pinned: bool = False
    repository_id: uuid_pkg.UUID | None = None
    folder: dict[str, Any] | None = None  # e.g. {"path": "blueprints"}


class DocumentUpdate(SQLModel):
    """Schema for updating a document."""

    title: str | None = None
    content: str | None = None
    type: str | None = None
    is_pinned: bool | None = None
    folder: dict[str, Any] | None = None


class Document(DocumentBase, UUIDMixin, TimestampMixin, UserOwnedMixin, table=True):
    """Documentation entry within a Product."""

    __tablename__ = "documents"

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

    # Folder path for organizing documents (e.g. {"path": "blueprints"})
    folder: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(
            JSONB,
            comment="Folder path for document organization (e.g. blueprints, plans, completions)",
        ),
    )

    # Relationships
    product: Optional["Product"] = Relationship(back_populates="documents")
