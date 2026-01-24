"""Document section and subsection models for hierarchical organization.

Sections allow users to create custom organizational categories for documents.
Each Product has its own set of sections (product-scoped).
"""

import uuid as uuid_pkg
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.product import Product


class DocumentSectionBase(SQLModel):
    """Base fields for DocumentSection."""

    name: str = Field(max_length=100, description="Display name (e.g., 'Technical Documentation')")
    slug: str = Field(max_length=50, index=True, description="URL-friendly identifier (e.g., 'technical')")
    position: int = Field(default=0, description="Order position for display")
    color: str | None = Field(default=None, max_length=7, description="Accent color as hex (e.g., '#c2410c')")
    icon: str | None = Field(default=None, max_length=50, description="Lucide icon name (e.g., 'Server')")
    is_default: bool = Field(default=False, description="System sections cannot be deleted")


class DocumentSectionCreate(SQLModel):
    """Schema for creating a document section."""

    product_id: uuid_pkg.UUID
    name: str
    slug: str
    position: int = 0
    color: str | None = None
    icon: str | None = None
    is_default: bool = False


class DocumentSectionUpdate(SQLModel):
    """Schema for updating a document section."""

    name: str | None = None
    slug: str | None = None
    position: int | None = None
    color: str | None = None
    icon: str | None = None


class DocumentSection(DocumentSectionBase, UUIDMixin, TimestampMixin, table=True):
    """Top-level section for organizing documents within a Product.

    Examples: "Technical Documentation", "Conceptual Documentation", "Custom Section"
    """

    __tablename__ = "document_sections"

    product_id: uuid_pkg.UUID = Field(
        foreign_key="products.id",
        nullable=False,
        index=True,
    )

    # Relationships
    product: Optional["Product"] = Relationship(back_populates="document_sections")
    subsections: list["DocumentSubsection"] = Relationship(
        back_populates="section",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "DocumentSubsection.position"},
    )
    documents: list["Document"] = Relationship(back_populates="document_section")


class DocumentSubsectionBase(SQLModel):
    """Base fields for DocumentSubsection."""

    name: str = Field(max_length=100, description="Display name (e.g., 'Backend')")
    slug: str = Field(max_length=50, index=True, description="URL-friendly identifier (e.g., 'backend')")
    position: int = Field(default=0, description="Order position within section")
    is_default: bool = Field(default=False, description="System subsections cannot be deleted")


class DocumentSubsectionCreate(SQLModel):
    """Schema for creating a document subsection."""

    section_id: uuid_pkg.UUID
    name: str
    slug: str
    position: int = 0
    is_default: bool = False


class DocumentSubsectionUpdate(SQLModel):
    """Schema for updating a document subsection."""

    name: str | None = None
    slug: str | None = None
    position: int | None = None


class DocumentSubsection(DocumentSubsectionBase, UUIDMixin, TimestampMixin, table=True):
    """Subsection within a DocumentSection.

    Examples within "Technical": "Backend", "Frontend", "Database"
    """

    __tablename__ = "document_subsections"

    section_id: uuid_pkg.UUID = Field(
        foreign_key="document_sections.id",
        nullable=False,
        index=True,
    )

    # Relationships
    section: Optional["DocumentSection"] = Relationship(back_populates="subsections")
    documents: list["Document"] = Relationship(back_populates="document_subsection")
