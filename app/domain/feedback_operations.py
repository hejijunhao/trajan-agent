"""Domain operations for Feedback model."""

import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.base_operations import BaseOperations
from app.models.feedback import Feedback, FeedbackCreate


class FeedbackOperations(BaseOperations[Feedback]):
    """CRUD operations for Feedback model."""

    def __init__(self) -> None:
        super().__init__(Feedback)

    async def create_feedback(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        data: FeedbackCreate,
    ) -> Feedback:
        """Create a new feedback submission."""
        feedback = Feedback(user_id=user_id, **data.model_dump())
        db.add(feedback)
        await db.flush()
        await db.refresh(feedback)
        return feedback

    async def list_by_user(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Feedback]:
        """Get all feedback submitted by a user."""
        statement = (
            select(Feedback)
            .where(Feedback.user_id == user_id)
            .order_by(Feedback.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_by_status(
        self,
        db: AsyncSession,
        status: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Feedback]:
        """Get feedback filtered by status (for admin use)."""
        statement = (
            select(Feedback)
            .where(Feedback.status == status)
            .order_by(Feedback.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_all(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Feedback]:
        """Get all feedback (for admin use)."""
        statement = select(Feedback).order_by(Feedback.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def update_ai_summary(
        self,
        db: AsyncSession,
        feedback_id: uuid_pkg.UUID,
        ai_summary: str,
    ) -> Feedback | None:
        """Update the AI-generated summary for a feedback item."""
        feedback = await self.get(db, feedback_id)
        if not feedback:
            return None

        feedback.ai_summary = ai_summary
        feedback.ai_processed_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(feedback)
        return feedback

    async def update_status(
        self,
        db: AsyncSession,
        feedback_id: uuid_pkg.UUID,
        status: str,
        admin_notes: str | None = None,
    ) -> Feedback | None:
        """Update feedback status (for admin use)."""
        feedback = await self.get(db, feedback_id)
        if not feedback:
            return None

        feedback.status = status
        if admin_notes is not None:
            feedback.admin_notes = admin_notes
        feedback.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(feedback)
        return feedback


feedback_ops = FeedbackOperations()
