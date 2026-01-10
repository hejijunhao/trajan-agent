
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.domain.user_operations import user_ops
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])


class UserRead(BaseModel):
    """User profile response."""

    id: str
    email: str | None
    display_name: str | None
    avatar_url: str | None
    github_username: str | None
    auth_provider: str | None
    created_at: str

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """User profile update request."""

    display_name: str | None = None
    avatar_url: str | None = None


def user_to_response(user: User) -> dict:
    """Convert User model to response dict."""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "github_username": user.github_username,
        "auth_provider": user.auth_provider,
        "created_at": user.created_at.isoformat(),
    }


@router.get("/me", response_model=UserRead)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """Get the current user's profile."""
    return user_to_response(current_user)


@router.patch("/me", response_model=UserRead)
async def update_current_user_profile(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's profile."""
    update_data = data.model_dump(exclude_unset=True)

    if not update_data:
        return user_to_response(current_user)

    updated_user = await user_ops.update(db, current_user, update_data)
    return user_to_response(updated_user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_user(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete the current user's account and all associated data.

    This action is irreversible. All products, work items, documents,
    and other user data will be permanently deleted.
    """
    deleted = await user_ops.delete(db, current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
