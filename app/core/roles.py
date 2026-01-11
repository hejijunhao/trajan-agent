"""Role hierarchy constants and utilities for organization member roles."""

from app.models.organization import MemberRole

# Hierarchy levels for organization member roles (higher = more privileges)
ROLE_HIERARCHY: dict[str, int] = {
    MemberRole.VIEWER.value: 0,
    MemberRole.MEMBER.value: 1,
    MemberRole.ADMIN.value: 2,
    MemberRole.OWNER.value: 3,
}


def get_role_level(role: str) -> int:
    """Get the hierarchy level for a role string."""
    return ROLE_HIERARCHY.get(role, 0)


def has_minimum_role(user_role: str, required_role: MemberRole) -> bool:
    """Check if a user's role meets or exceeds the required role level."""
    return get_role_level(user_role) >= get_role_level(required_role.value)
