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
        products → org_members → organizations → users (App DB) → users (Supabase Auth)
    """

    users: list[UUID] = field(default_factory=list)
    organizations: list[UUID] = field(default_factory=list)
    products: list[UUID] = field(default_factory=list)
    org_members: list[tuple[UUID, UUID]] = field(default_factory=list)

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

    def unregister_product(self, product_id: UUID) -> None:
        """Remove a product from tracking (e.g. after explicit deletion in a test)."""
        if product_id in self.products:
            self.products.remove(product_id)

    @property
    def summary(self) -> str:
        return (
            f"Tracked resources: {len(self.users)} users, "
            f"{len(self.organizations)} orgs, "
            f"{len(self.products)} products, "
            f"{len(self.org_members)} org_members"
        )
