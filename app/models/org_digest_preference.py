"""Org-scoped email digest preferences.

Replaces the global digest fields on UserPreferences with a per-org model,
so users can configure different digest frequencies per organization.
"""

import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class OrgDigestPreference(SQLModel, table=True):
    """
    Per-organization digest preferences for a user.

    One row per (user_id, organization_id) pair. Each org the user belongs to
    can have its own frequency, timezone, hour, and product filter.
    """

    __tablename__ = "org_digest_preferences"
    __table_args__ = (
        Index(
            "ix_org_digest_pref_user_org",
            "user_id",
            "organization_id",
            unique=True,
        ),
    )

    id: uuid_pkg.UUID = Field(
        default_factory=uuid_pkg.uuid4,
        primary_key=True,
        nullable=False,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )

    # CASCADE added via migration 22beb16d16fa
    user_id: uuid_pkg.UUID = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
    )

    organization_id: uuid_pkg.UUID = Field(
        foreign_key="organizations.id",
        nullable=False,
        index=True,
    )

    # "none" | "daily" | "weekly"
    email_digest: str = Field(default="none", max_length=20)

    # NULL = all accessible products in this org
    digest_product_ids: list[str] | None = Field(
        default=None,
        sa_column=Column(
            JSONB,
            nullable=True,
            comment="Product UUIDs to include. NULL = all accessible products.",
        ),
    )

    digest_timezone: str = Field(default="UTC", max_length=50)
    digest_hour: int = Field(default=17)  # 0-23

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
