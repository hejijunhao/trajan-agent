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

from app.api.v1.organizations.crud import (
    create_organization,
    delete_organization,
    get_organization,
    list_organizations,
    list_plans,
    transfer_ownership,
    update_organization,
)

# Import route handlers from sub-modules
from app.api.v1.organizations.digest_preferences import (
    get_digest_preferences,
    update_digest_preferences,
)
from app.api.v1.organizations.member_access import (
    bulk_set_member_product_access,
    get_member_product_access,
)
from app.api.v1.organizations.members import (
    add_member,
    link_member_github,
    list_members,
    remove_member,
    resend_invite,
    unlink_member_github,
    update_member_role,
)
from app.api.v1.organizations.repositories import list_org_repositories
from app.api.v1.organizations.settings import get_settings, update_settings
from app.api.v1.organizations.team_activity import get_team_activity
from app.api.v1.organizations.team_summaries import get_team_summaries

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
router.add_api_route(
    "/{org_id}/members/{user_id}/link-github", link_member_github, methods=["PATCH"]
)
router.add_api_route(
    "/{org_id}/members/{user_id}/link-github", unlink_member_github, methods=["DELETE"]
)

# Subscription routes

# Repository routes (for downgrade flows)
router.add_api_route("/{org_id}/repositories", list_org_repositories, methods=["GET"])

# Member product access routes
router.add_api_route(
    "/{org_id}/members/{member_id}/product-access", get_member_product_access, methods=["GET"]
)
router.add_api_route(
    "/{org_id}/members/{member_id}/product-access/bulk",
    bulk_set_member_product_access,
    methods=["POST"],
)

# Settings routes
router.add_api_route("/{org_id}/settings", get_settings, methods=["GET"])
router.add_api_route("/{org_id}/settings", update_settings, methods=["PATCH"])

# Team activity routes
router.add_api_route("/{org_id}/team-activity", get_team_activity, methods=["GET"])
router.add_api_route("/{org_id}/team-activity/summaries", get_team_summaries, methods=["GET"])

# Digest preference routes
router.add_api_route(
    "/{org_id}/digest-preferences", get_digest_preferences, methods=["GET"]
)
router.add_api_route(
    "/{org_id}/digest-preferences", update_digest_preferences, methods=["PATCH"]
)

__all__ = ["router"]
