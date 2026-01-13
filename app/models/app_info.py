import uuid as uuid_pkg
from typing import TYPE_CHECKING, Any, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.product import Product


class AppInfoBase(SQLModel):
    """Base fields for AppInfo key-value store."""

    key: str | None = Field(default=None, max_length=255, index=True)
    value: str | None = Field(default=None)
    category: str | None = Field(default=None, max_length=50)  # e.g. env_var, url, credential, note
    is_secret: bool | None = Field(default=False)
    description: str | None = Field(default=None, max_length=500)


class AppInfoCreate(SQLModel):
    """Schema for creating an app info entry."""

    product_id: uuid_pkg.UUID
    key: str
    value: str
    category: str | None = None
    is_secret: bool = False
    description: str | None = None


class AppInfoUpdate(SQLModel):
    """Schema for updating an app info entry."""

    key: str | None = None
    value: str | None = None
    category: str | None = None
    is_secret: bool | None = None
    description: str | None = None


class AppInfoBulkEntry(SQLModel):
    """Schema for a single entry in bulk create."""

    key: str
    value: str
    category: str | None = None
    is_secret: bool = False
    description: str | None = None


class AppInfoBulkCreate(SQLModel):
    """Request schema for bulk creating app info entries."""

    product_id: uuid_pkg.UUID
    entries: list[AppInfoBulkEntry]


class AppInfoBulkResponse(SQLModel):
    """Response schema for bulk create operation."""

    created: list[dict[str, Any]]  # Created entries
    skipped: list[str]  # Keys that were skipped (duplicates)


class AppInfoExportEntry(SQLModel):
    """Schema for a single exported entry with revealed value."""

    key: str
    value: str
    category: str | None = None
    is_secret: bool = False
    description: str | None = None


class AppInfoExportResponse(SQLModel):
    """Response schema for export operation."""

    entries: list[AppInfoExportEntry]


class AppInfo(AppInfoBase, UUIDMixin, TimestampMixin, UserOwnedMixin, table=True):
    """Key-value store for project context (env vars, URLs, notes)."""

    __tablename__ = "app_info"

    product_id: uuid_pkg.UUID | None = Field(
        default=None,
        foreign_key="products.id",
        index=True,
    )

    # Relationships
    product: Optional["Product"] = Relationship(back_populates="app_info_entries")
