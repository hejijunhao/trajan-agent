"""GitHub token resolution for background jobs (no request context).

Extracted from the per-request _resolve_github_token() in progress.py.
For background/cron jobs there is no current_user, so we resolve tokens
purely by org membership role priority: owner → admin.
"""

import logging
import uuid as uuid_pkg

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class TokenResolver:
    """Resolve GitHub tokens for organizations without a request context."""

    async def resolve_for_org(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
    ) -> str | None:
        """
        Find a GitHub token from an org owner or admin.

        Priority: owner's token first, then admins (ordered by role).
        Returns the first valid decrypted token, or None.
        """
        from app.domain import org_member_ops
        from app.domain.preferences_operations import preferences_ops

        members = await org_member_ops.get_members_with_tokens(db, organization_id)

        for member in members:
            member_prefs = await preferences_ops.get_by_user_id(db, member.user_id)
            token = preferences_ops.get_decrypted_token(member_prefs) if member_prefs else None
            if token:
                return token

        return None


token_resolver = TokenResolver()
