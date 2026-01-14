"""Pydantic schemas for repository documentation scanning endpoints."""

from datetime import datetime

from pydantic import BaseModel


class RepoDocFile(BaseModel):
    """A single documentation file from a repository."""

    path: str  # Full path from repo root (e.g., "docs/api.md")
    name: str  # Filename only (e.g., "api.md")
    size: int  # File size in bytes
    sha: str  # Git blob SHA


class RepoDocDirectory(BaseModel):
    """A directory containing documentation files."""

    path: str  # Directory path (e.g., "docs")
    name: str  # Directory name only
    files: list[RepoDocFile] = []
    directories: list["RepoDocDirectory"] = []


class RepoDocsTree(BaseModel):
    """Documentation tree for a single repository."""

    repository_id: str
    repository_name: str  # Full name (e.g., "owner/repo")
    branch: str
    files: list[RepoDocFile] = []  # Root-level doc files
    directories: list[RepoDocDirectory] = []  # Doc directories


class RepoDocsTreeResponse(BaseModel):
    """Response for GET /products/{id}/repo-docs-tree."""

    repositories: list[RepoDocsTree]
    total_files: int
    fetched_at: datetime


class RepoDocContent(BaseModel):
    """Response for GET /repositories/{id}/file-content."""

    path: str
    content: str
    size: int
    sha: str
    repository_id: str
    repository_name: str
    branch: str
    truncated: bool = False  # True if content was truncated due to size
