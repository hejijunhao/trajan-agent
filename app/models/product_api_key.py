import uuid as uuid_pkg
from datetime import datetime

from sqlalchemy import Column, DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin, UUIDMixin


class ProductApiKey(UUIDMixin, TimestampMixin, SQLModel, table=True):
    """API key for external access to a product's public endpoints.

    Keys are hashed (SHA-256) before storage — the raw key is only
    returned once at creation time and never persisted.
    """

    __tablename__ = "product_api_keys"

    product_id: uuid_pkg.UUID = Field(
        foreign_key="products.id",
        nullable=False,
        index=True,
    )
    key_hash: str = Field(
        sa_column=Column(String(64), unique=True, index=True, nullable=False),
    )
    key_prefix: str = Field(max_length=16)
    name: str = Field(max_length=255)
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    )
    created_by_user_id: uuid_pkg.UUID = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
    )
    last_used_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class ProductApiKeyCreate(SQLModel):
    """Schema for creating an API key."""

    name: str = Field(max_length=255)
    scopes: list[str] = Field(min_length=1)


class ProductApiKeyRead(SQLModel):
    """Schema for reading an API key (never exposes the hash)."""

    id: uuid_pkg.UUID
    product_id: uuid_pkg.UUID
    key_prefix: str
    name: str
    scopes: list[str]
    created_by_user_id: uuid_pkg.UUID
    created_at: datetime
    last_used_at: datetime | None


class ProductApiKeyCreateResponse(ProductApiKeyRead):
    """Response after creating a key — includes the raw key (shown once)."""

    raw_key: str
