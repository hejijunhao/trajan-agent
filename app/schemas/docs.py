"""Pydantic schemas for documentation endpoints."""

from datetime import datetime

from pydantic import BaseModel


class GenerateDocsResponse(BaseModel):
    """Response for POST /products/{id}/generate-docs."""

    status: str  # "started", "already_running"
    message: str


class DocsStatusResponse(BaseModel):
    """Response for GET /products/{id}/docs-status."""

    status: str  # "idle", "generating", "completed", "failed"
    progress: dict | None = None
    error: str | None = None
    last_generated_at: datetime | None = None


class DocumentGrouped(BaseModel):
    """A single document in the grouped response."""

    id: str
    title: str
    content: str | None
    type: str | None
    is_pinned: bool
    folder: dict | None
    created_at: str
    updated_at: str


class DocumentsGroupedResponse(BaseModel):
    """Response for GET /products/{id}/documents/grouped."""

    changelog: list[DocumentGrouped]
    blueprints: list[DocumentGrouped]
    plans: list[DocumentGrouped]
    executing: list[DocumentGrouped]
    completions: list[DocumentGrouped]
    archive: list[DocumentGrouped]


class ChangeEntryRequest(BaseModel):
    """A single changelog entry."""

    category: str  # "Added", "Changed", "Fixed", "Removed"
    description: str


class AddChangelogEntryRequest(BaseModel):
    """Request body for POST /products/{id}/changelog/add-entry."""

    version: str | None = None
    changes: list[ChangeEntryRequest]
