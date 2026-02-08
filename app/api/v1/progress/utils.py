"""Shared utilities for Progress API endpoints."""

import logging
import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import repository_ops
from app.domain.preferences_operations import preferences_ops
from app.models import User
from app.models.repository import Repository
from app.services.github import GitHubReadOperations
from app.services.github.exceptions import GitHubRepoRenamed

logger = logging.getLogger(__name__)


async def handle_repo_rename(
    db: AsyncSession,
    github: GitHubReadOperations,
    repo: Repository,
    exc: GitHubRepoRenamed,
) -> Repository | None:
    """Handle a GitHub repository rename by resolving the new name and updating the database.

    Args:
        db: Database session
        github: GitHub service for resolving repo ID to name
        repo: The Repository with the old name
        exc: The GitHubRepoRenamed exception with rename details

    Returns:
        Updated Repository with new full_name, or None if update failed
    """
    if repo.id is None:
        return None

    new_full_name = exc.new_full_name

    # If we only have repo_id (GitHub redirected to ID-based URL), resolve it
    if not new_full_name and exc.repo_id:
        try:
            logger.info(f"Resolving GitHub repo ID {exc.repo_id} to get current name...")
            github_repo = await github.get_repo_by_id(exc.repo_id)
            new_full_name = github_repo.full_name
            logger.info(f"Resolved repo ID {exc.repo_id} → {new_full_name}")
        except Exception as e:
            logger.error(f"Failed to resolve repo ID {exc.repo_id}: {e}")
            return None

    if not new_full_name:
        logger.error(f"Cannot update repo {repo.full_name}: no new name available")
        return None

    logger.info(f"Repository renamed on GitHub: {repo.full_name} → {new_full_name}")

    updated_repo = await repository_ops.update_full_name(db, repo.id, new_full_name)
    if updated_repo:
        logger.info(f"Updated repository record: {repo.full_name} → {new_full_name}")
        await db.commit()
    else:
        logger.error(f"Failed to update repository record for {repo.full_name}")

    return updated_repo


def extract_focus_area(file_path: str) -> str:
    """Extract the top-level directory from a file path.

    Examples:
        "backend/app/api/v1/timeline.py" -> "backend"
        "frontend/src/components/Button.tsx" -> "frontend"
        "README.md" -> "."
    """
    parts = file_path.split("/")
    if len(parts) > 1:
        return parts[0]
    return "."  # Root-level files


def get_period_start(period: str) -> datetime:
    """Convert period string to start datetime.

    Args:
        period: One of "24h", "48h", "7d", "14d", "30d", "90d", "365d"

    Returns:
        UTC datetime for the start of the period
    """
    now = datetime.now(UTC)

    period_map = {
        "24h": timedelta(hours=24),
        "48h": timedelta(hours=48),
        "7d": timedelta(days=7),
        "14d": timedelta(days=14),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "365d": timedelta(days=365),
    }

    delta = period_map.get(period, timedelta(days=7))  # Default to 7d
    return now - delta


def get_extended_period(period: str) -> str:
    """Get an extended period string for fetching comparison data."""
    period_map = {
        "24h": "48h",
        "48h": "7d",
        "7d": "14d",
        "14d": "30d",
        "30d": "90d",
        "90d": "365d",
        "365d": "365d",  # Can't extend beyond a year easily
    }
    return period_map.get(period, "90d")


def get_period_days(period: str) -> int:
    """Get the number of days for a period string."""
    period_days = {
        "24h": 1,
        "48h": 2,
        "7d": 7,
        "14d": 14,
        "30d": 30,
        "90d": 90,
        "365d": 365,
    }
    return period_days.get(period, 7)


async def resolve_github_token(
    db: AsyncSession,
    current_user: User,
    product_id: uuid_pkg.UUID,
) -> str | None:
    """Resolve a GitHub token for API access.

    Priority:
    1. Current user's own token (preferred — respects their repo access scope)
    2. Org owner/admin token (fallback for collaborative read access)
    """
    from app.domain import org_member_ops, product_ops

    # 1. Try current user's token first
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    if token:
        return token

    # 2. Fallback: find a token from an org admin/owner
    product = await product_ops.get(db, product_id)
    if not product or not product.organization_id:
        return None

    members = await org_member_ops.get_members_with_tokens(db, product.organization_id)
    for member in members:
        member_prefs = await preferences_ops.get_by_user_id(db, member.user_id)
        fallback = preferences_ops.get_decrypted_token(member_prefs) if member_prefs else None
        if fallback:
            return fallback

    return None


def generate_daily_activity(daily_counts: dict[str, int], period: str) -> list[dict[str, Any]]:
    """Generate daily activity list with all days in period."""
    days = get_period_days(period)
    today = datetime.now(UTC).date()

    activity = []
    for i in range(days - 1, -1, -1):  # Oldest to newest
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        activity.append(
            {
                "date": date_str,
                "commits": daily_counts.get(date_str, 0),
            }
        )

    return activity


# Backward compatibility aliases (underscore-prefixed versions)
_handle_repo_rename = handle_repo_rename
_resolve_github_token = resolve_github_token
_generate_daily_activity = generate_daily_activity
_get_extended_period = get_extended_period
