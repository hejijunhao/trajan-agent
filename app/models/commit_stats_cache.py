"""Commit stats cache model for GitHub commit statistics."""

import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, text
from sqlmodel import Field, SQLModel


class CommitStatsCache(SQLModel, table=True):
    """
    Cached commit statistics from GitHub.

    This is a shared cache (not user-scoped) because:
    1. Git SHAs are immutable - stats never change
    2. Stats are public - same for all viewers
    3. Avoids N duplicate rows for N users viewing same commit

    Lookup is by (repository_full_name, commit_sha) since:
    - Same SHA can exist in forks with different stats
    - full_name is compact and available in timeline context
    """

    __tablename__ = "commit_stats_cache"
    __table_args__ = (
        Index(
            "ix_commit_stats_cache_repo_sha",
            "repository_full_name",
            "commit_sha",
            unique=True,
        ),
        Index("ix_commit_stats_cache_created_at", "created_at"),
    )

    id: uuid_pkg.UUID = Field(
        default_factory=uuid_pkg.uuid4,
        primary_key=True,
        nullable=False,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )

    repository_full_name: str = Field(
        max_length=500,
        nullable=False,
        description="GitHub repo full name (owner/repo)",
    )
    commit_sha: str = Field(
        max_length=40,
        nullable=False,
        description="Full 40-character git SHA",
    )

    additions: int = Field(default=0, nullable=False)
    deletions: int = Field(default=0, nullable=False)
    files_changed: int = Field(default=0, nullable=False)

    created_at: datetime = Field(  # type: ignore[call-overload]
        default_factory=lambda: datetime.now(UTC),
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": text("now()")},
    )
