"""Documents API package — split for maintainability.

Modules:
- crud.py — Basic CRUD operations + product-scoped endpoints
- lifecycle.py — Plan state transitions (move-to-executing, move-to-completed, archive)
- sync.py — GitHub synchronization endpoints
- refresh.py — Document refresh endpoints
- repo_docs.py — Repository documentation scanning endpoints
"""

from fastapi import APIRouter

# Import route handlers from sub-modules
from app.api.v1.documents.crud import (
    add_changelog_entry,
    create_document,
    delete_document,
    get_document,
    get_documents_grouped,
    list_documents,
    serialize_document,
    update_document,
)
from app.api.v1.documents.lifecycle import (
    archive_document,
    move_to_completed,
    move_to_executing,
)
from app.api.v1.documents.refresh import (
    refresh_all_documents,
    refresh_document,
)
from app.api.v1.documents.repo_docs import (
    get_repo_docs_tree,
    get_repo_file_content,
)
from app.api.v1.documents.sync import (
    get_docs_sync_status,
    import_docs_from_repo,
    pull_remote_changes,
    sync_docs_to_repo,
)

router = APIRouter(prefix="/documents", tags=["documents"])

# CRUD routes
router.add_api_route("", list_documents, methods=["GET"], response_model=list[dict])
router.add_api_route("/{document_id}", get_document, methods=["GET"])
router.add_api_route("", create_document, methods=["POST"], status_code=201)
router.add_api_route("/{document_id}", update_document, methods=["PATCH"])
router.add_api_route("/{document_id}", delete_document, methods=["DELETE"], status_code=204)

# Product-scoped routes
router.add_api_route(
    "/products/{product_id}/grouped", get_documents_grouped, methods=["GET"]
)
router.add_api_route(
    "/products/{product_id}/changelog/add-entry", add_changelog_entry, methods=["POST"]
)

# Lifecycle routes
router.add_api_route("/{document_id}/move-to-executing", move_to_executing, methods=["POST"])
router.add_api_route("/{document_id}/move-to-completed", move_to_completed, methods=["POST"])
router.add_api_route("/{document_id}/archive", archive_document, methods=["POST"])

# Sync routes
router.add_api_route(
    "/products/{product_id}/import-docs", import_docs_from_repo, methods=["POST"]
)
router.add_api_route(
    "/products/{product_id}/docs-sync-status", get_docs_sync_status, methods=["GET"]
)
router.add_api_route("/{document_id}/pull-remote", pull_remote_changes, methods=["POST"])
router.add_api_route("/products/{product_id}/sync-docs", sync_docs_to_repo, methods=["POST"])

# Refresh routes
router.add_api_route("/{document_id}/refresh", refresh_document, methods=["POST"])
router.add_api_route(
    "/products/{product_id}/refresh-all-docs", refresh_all_documents, methods=["POST"]
)

# Repository docs routes (read-only scanning)
router.add_api_route(
    "/products/{product_id}/repo-docs-tree", get_repo_docs_tree, methods=["GET"]
)
router.add_api_route(
    "/repositories/{repository_id}/file-content", get_repo_file_content, methods=["GET"]
)

__all__ = ["router", "serialize_document"]
