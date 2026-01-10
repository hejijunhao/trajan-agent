import uuid as uuid_pkg

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserOperations:
    """Operations for User model."""

    async def get_by_id(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> User | None:
        """Get a user by ID."""
        statement = select(User).where(User.id == user_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        user: User,
        obj_in: dict,
    ) -> User:
        """Update a user's profile fields."""
        for field, value in obj_in.items():
            if value is not None and hasattr(user, field):
                setattr(user, field, value)
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    async def delete(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> bool:
        """
        Delete a user and all their data.

        Note: Related data (products, work items, etc.) will cascade delete
        via foreign key constraints.
        """
        user = await self.get_by_id(db, user_id)
        if user:
            await db.delete(user)
            await db.flush()
            return True
        return False


user_ops = UserOperations()
