"""Domain operations for Announcement model."""

from datetime import UTC, datetime

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import Case

from app.domain.base_operations import BaseOperations
from app.models.announcement import Announcement, AnnouncementVariant


class AnnouncementOperations(BaseOperations[Announcement]):
    """CRUD operations for Announcement model."""

    def __init__(self) -> None:
        super().__init__(Announcement)

    async def get_active(
        self,
        db: AsyncSession,
    ) -> list[Announcement]:
        """Get all currently active announcements.

        Returns announcements where:
        - is_active = true
        - starts_at IS NULL OR starts_at <= NOW()
        - ends_at IS NULL OR ends_at > NOW()

        Ordered by: variant priority (error > warning > info), then created_at DESC
        """
        now = datetime.now(UTC)

        # Build query with time-based filtering
        statement = (
            select(Announcement)
            .where(
                Announcement.is_active == True,  # type: ignore[arg-type]  # noqa: E712
                # Check starts_at: NULL means show immediately, otherwise must be past
                (Announcement.starts_at.is_(None))  # type: ignore[union-attr]
                | (Announcement.starts_at <= now),  # type: ignore[operator]
                # Check ends_at: NULL means no end, otherwise must be in future
                (Announcement.ends_at.is_(None))  # type: ignore[union-attr]
                | (Announcement.ends_at > now),  # type: ignore[operator]
            )
            .order_by(
                # Priority order: error (most important) > warning > info
                _variant_priority_case(),
                Announcement.created_at.desc(),  # type: ignore[attr-defined]
            )
        )

        result = await db.execute(statement)
        return list(result.scalars().all())


def _variant_priority_case() -> Case[int]:
    """Create a case expression for variant priority sorting.

    Returns lower numbers for higher priority variants.
    """
    return case(
        (Announcement.variant == AnnouncementVariant.ERROR, 1),  # type: ignore[arg-type]
        (Announcement.variant == AnnouncementVariant.WARNING, 2),  # type: ignore[arg-type]
        (Announcement.variant == AnnouncementVariant.INFO, 3),  # type: ignore[arg-type]
        else_=4,
    )


announcement_ops = AnnouncementOperations()
