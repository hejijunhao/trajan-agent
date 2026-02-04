"""Organizations API package — split for maintainability.

Modules:
- schemas.py — Response/request schemas
- helpers.py — Shared helper functions
- crud.py — Organization CRUD operations
- members.py — Member management endpoints
- member_access.py — Member product access endpoints
- subscriptions.py — Subscription endpoints
- repositories.py — Organization-wide repository listing
- settings.py — Organization settings endpoints
"""

from fastapi import APIRouter

# Import route handlers from sub-modules
from app.api.v1.organizations.crud import (
    create_organization,
    delete_organization,
    get_organization,
    list_organizations,
    list_plans,
    transfer_ownership,
    update_organization,
)
from app.api.v1.organizations.member_access import get_member_product_access
from app.api.v1.organizations.members import (
    add_member,
    list_members,
    remove_member,
    resend_invite,
    update_member_role,
)
from app.api.v1.organizations.repositories import list_org_repositories
from app.api.v1.organizations.settings import get_settings, update_settings
from app.api.v1.organizations.subscriptions import get_repo_limit_status, get_subscription

router = APIRouter(prefix="/organizations", tags=["organizations"])

# Organization CRUD routes
router.add_api_route("", list_organizations, methods=["GET"])
router.add_api_route("", create_organization, methods=["POST"], status_code=201)
router.add_api_route("/plans", list_plans, methods=["GET"])
router.add_api_route("/{org_id}", get_organization, methods=["GET"])
router.add_api_route("/{org_id}", update_organization, methods=["PATCH"])
router.add_api_route("/{org_id}", delete_organization, methods=["DELETE"], status_code=204)
router.add_api_route("/{org_id}/transfer-ownership", transfer_ownership, methods=["POST"])

# Member management routes
router.add_api_route("/{org_id}/members", list_members, methods=["GET"])
router.add_api_route("/{org_id}/members", add_member, methods=["POST"], status_code=201)
router.add_api_route("/{org_id}/members/{member_id}", update_member_role, methods=["PATCH"])
router.add_api_route(
    "/{org_id}/members/{member_id}", remove_member, methods=["DELETE"], status_code=204
)
router.add_api_route("/{org_id}/members/{member_id}/resend-invite", resend_invite, methods=["POST"])

# Subscription routes
router.add_api_route("/{org_id}/subscription", get_subscription, methods=["GET"])
router.add_api_route("/{org_id}/repo-limit-status", get_repo_limit_status, methods=["GET"])

# Repository routes (for downgrade flows)
router.add_api_route("/{org_id}/repositories", list_org_repositories, methods=["GET"])

# Member product access routes
router.add_api_route(
    "/{org_id}/members/{member_id}/product-access", get_member_product_access, methods=["GET"]
)

# Settings routes
router.add_api_route("/{org_id}/settings", get_settings, methods=["GET"])
router.add_api_route("/{org_id}/settings", update_settings, methods=["PATCH"])

__all__ = ["router"]
