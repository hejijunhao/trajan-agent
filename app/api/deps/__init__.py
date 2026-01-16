"""API dependencies - re-exports from submodules for backwards compatibility."""

from .auth import (
    CurrentUser,
    DbSession,
    get_current_user,
    get_current_user_optional,
    get_db_with_rls,
    get_jwks,
    get_signing_key,
    security,
)
from .feature_gates import (
    FeatureGate,
    SubscriptionContext,
    get_subscription_context,
    require_agent_enabled,
)
from .organization import (
    get_current_organization,
    require_org_admin,
    require_org_owner,
    require_system_admin,
)
from .product_access import (
    ProductAccessContext,
    check_product_admin_access,
    check_product_editor_access,
    get_product_access,
    require_product_admin,
    require_product_editor,
    require_variables_access,
)

__all__ = [
    # Auth
    "security",
    "get_jwks",
    "get_signing_key",
    "get_current_user",
    "get_current_user_optional",
    "get_db_with_rls",
    "DbSession",
    "CurrentUser",
    # Organization
    "get_current_organization",
    "require_org_admin",
    "require_org_owner",
    "require_system_admin",
    # Feature gates
    "SubscriptionContext",
    "get_subscription_context",
    "FeatureGate",
    "require_agent_enabled",
    # Product access
    "ProductAccessContext",
    "get_product_access",
    "require_product_editor",
    "require_product_admin",
    "require_variables_access",
    "check_product_editor_access",
    "check_product_admin_access",
]
