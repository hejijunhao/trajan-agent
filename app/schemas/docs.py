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


# =============================================================================
# Phase 2: GitHub Sync Schemas
# =============================================================================


class ImportDocsResponse(BaseModel):
    """Response for POST /products/{id}/import-docs."""

    imported: int  # New documents created
    updated: int  # Existing documents updated
    skipped: int  # Unchanged documents skipped


class SyncDocsRequest(BaseModel):
    """Request body for POST /products/{id}/sync-docs."""

    document_ids: list[str] | None = None  # Specific docs to sync, or all with local changes
    message: str = "Sync documentation from Trajan"  # Commit message


class SyncDocsResponse(BaseModel):
    """Response for POST /products/{id}/sync-docs."""

    success: bool
    files_synced: int
    commit_sha: str | None = None
    errors: list[str] = []


class DocumentSyncStatusResponse(BaseModel):
    """Sync status for a single document."""

    document_id: str
    status: str  # "synced", "local_changes", "remote_changes", "conflict", "error"
    local_sha: str | None = None
    remote_sha: str | None = None
    error: str | None = None


class DocsSyncStatusResponse(BaseModel):
    """Response for GET /products/{id}/docs-sync-status."""

    documents: list[DocumentSyncStatusResponse]
    has_local_changes: bool
    has_remote_changes: bool


class PullRemoteRequest(BaseModel):
    """Request body for POST /documents/{id}/pull-remote."""

    pass  # No body needed, but keeping for future expansion


# =============================================================================
# Phase 7: Document Refresh Schemas
# =============================================================================


class RefreshDocumentResponse(BaseModel):
    """Response for POST /documents/{id}/refresh."""

    document_id: str
    status: str  # "updated", "unchanged", "error"
    changes_summary: str | None = None
    error: str | None = None


class RefreshDocumentDetailResponse(BaseModel):
    """Detail for a single document in bulk refresh."""

    document_id: str
    status: str  # "updated", "unchanged", "error"
    changes_summary: str | None = None
    error: str | None = None


class BulkRefreshResponse(BaseModel):
    """Response for POST /products/{id}/refresh-all-docs."""

    checked: int
    updated: int
    unchanged: int
    errors: int
    details: list[RefreshDocumentDetailResponse] = []
