"""Test resource tracker for full-stack integration tests.

Tracks all resources created during tests so they can be cleaned up
in reverse FK-dependency order, even if tests fail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class ResourceTracker:
    """Tracks all test resources for guaranteed cleanup.

    Resources are stored in creation order and cleaned up in reverse
    order, respecting FK dependencies:
        product children → products → org_members → organizations
        → users (App DB) → users (Supabase Auth)

    Product children (repositories, documents, work_items, app_info) are
    automatically deleted during the product cascade. They are tracked here
    for verification purposes and for cases where a resource is created
    outside a product context.
    """

    users: list[UUID] = field(default_factory=list)
    organizations: list[UUID] = field(default_factory=list)
    products: list[UUID] = field(default_factory=list)
    org_members: list[tuple[UUID, UUID]] = field(default_factory=list)

    # Product children — cleaned via product cascade, tracked for verification
    repositories: list[UUID] = field(default_factory=list)
    documents: list[UUID] = field(default_factory=list)
    work_items: list[UUID] = field(default_factory=list)
    app_info: list[UUID] = field(default_factory=list)

    # User-scoped resources
    feedback: list[UUID] = field(default_factory=list)
    referral_codes: list[UUID] = field(default_factory=list)

    # ── Core entity registration ──────────────────────────────────────

    def register_user(self, user_id: UUID) -> None:
        if user_id not in self.users:
            self.users.append(user_id)
            logger.debug(f"Tracked user: {user_id}")

    def register_org(self, org_id: UUID) -> None:
        if org_id not in self.organizations:
            self.organizations.append(org_id)
            logger.debug(f"Tracked organization: {org_id}")

    def register_product(self, product_id: UUID) -> None:
        if product_id not in self.products:
            self.products.append(product_id)
            logger.debug(f"Tracked product: {product_id}")

    def register_org_member(self, org_id: UUID, user_id: UUID) -> None:
        pair = (org_id, user_id)
        if pair not in self.org_members:
            self.org_members.append(pair)
            logger.debug(f"Tracked org member: org={org_id}, user={user_id}")

    # ── Product children registration ─────────────────────────────────

    def register_repository(self, repo_id: UUID) -> None:
        if repo_id not in self.repositories:
            self.repositories.append(repo_id)
            logger.debug(f"Tracked repository: {repo_id}")

    def register_document(self, doc_id: UUID) -> None:
        if doc_id not in self.documents:
            self.documents.append(doc_id)
            logger.debug(f"Tracked document: {doc_id}")

    def register_work_item(self, work_item_id: UUID) -> None:
        if work_item_id not in self.work_items:
            self.work_items.append(work_item_id)
            logger.debug(f"Tracked work item: {work_item_id}")

    def register_app_info(self, app_info_id: UUID) -> None:
        if app_info_id not in self.app_info:
            self.app_info.append(app_info_id)
            logger.debug(f"Tracked app info: {app_info_id}")

    # ── User-scoped resource registration ─────────────────────────────

    def register_feedback(self, feedback_id: UUID) -> None:
        if feedback_id not in self.feedback:
            self.feedback.append(feedback_id)
            logger.debug(f"Tracked feedback: {feedback_id}")

    def register_referral_code(self, referral_code_id: UUID) -> None:
        if referral_code_id not in self.referral_codes:
            self.referral_codes.append(referral_code_id)
            logger.debug(f"Tracked referral code: {referral_code_id}")

    # ── Unregister (for explicit test deletions) ──────────────────────

    def unregister_product(self, product_id: UUID) -> None:
        """Remove a product from tracking (e.g. after explicit deletion in a test)."""
        if product_id in self.products:
            self.products.remove(product_id)

    def unregister_repository(self, repo_id: UUID) -> None:
        if repo_id in self.repositories:
            self.repositories.remove(repo_id)

    def unregister_document(self, doc_id: UUID) -> None:
        if doc_id in self.documents:
            self.documents.remove(doc_id)

    # ── Diagnostics ───────────────────────────────────────────────────

    @property
    def summary(self) -> str:
        parts = [
            f"{len(self.users)} users",
            f"{len(self.organizations)} orgs",
            f"{len(self.products)} products",
            f"{len(self.org_members)} org_members",
        ]
        # Only include non-empty child counts to keep output concise
        if self.repositories:
            parts.append(f"{len(self.repositories)} repos")
        if self.documents:
            parts.append(f"{len(self.documents)} docs")
        if self.work_items:
            parts.append(f"{len(self.work_items)} work_items")
        if self.app_info:
            parts.append(f"{len(self.app_info)} app_info")
        if self.feedback:
            parts.append(f"{len(self.feedback)} feedback")
        if self.referral_codes:
            parts.append(f"{len(self.referral_codes)} referral_codes")
        return f"Tracked resources: {', '.join(parts)}"

    @property
    def total_count(self) -> int:
        """Total number of tracked resources across all types."""
        return (
            len(self.users)
            + len(self.organizations)
            + len(self.products)
            + len(self.org_members)
            + len(self.repositories)
            + len(self.documents)
            + len(self.work_items)
            + len(self.app_info)
            + len(self.feedback)
            + len(self.referral_codes)
        )
