"""Referral API endpoints for the user-based referral system."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.config import settings
from app.domain.referral_operations import referral_ops

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/referrals", tags=["referrals"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class ReferralCodeResponse(BaseModel):
    """Single referral code response."""

    id: str
    code: str
    status: str  # "available", "pending", "converted"
    created_at: datetime
    redeemed_at: datetime | None = None
    redeemed_by_name: str | None = None
    converted_at: datetime | None = None

    class Config:
        from_attributes = True


class ReferralCodesListResponse(BaseModel):
    """User's referral codes with capacity info."""

    codes: list[ReferralCodeResponse]
    stats: "ReferralStatsResponse"


class ReferralStatsResponse(BaseModel):
    """Referral statistics for a user."""

    total_codes: int
    available: int
    pending: int
    converted: int
    remaining_invites: int
    invite_limit: int


class ValidateCodeResponse(BaseModel):
    """Public: Validate referral code response."""

    valid: bool
    referrer_name: str | None = None


class RedeemCodeRequest(BaseModel):
    """Request to redeem a referral code."""

    code: str


class RedeemCodeResponse(BaseModel):
    """Response after redeeming a referral code."""

    success: bool
    message: str
    referrer_name: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Public Endpoints (no auth required)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/validate/{code}", response_model=ValidateCodeResponse)
async def validate_referral_code(
    code: str,
    db: DbSession,
) -> ValidateCodeResponse:
    """
    Public endpoint: Validate a referral code.

    Returns referrer's name if code is valid and unredeemed.
    Used by the referral landing page to show "Sarah invited you".
    """
    referral = await referral_ops.validate_code(db, code)

    if not referral:
        return ValidateCodeResponse(valid=False, referrer_name=None)

    # Get referrer's display name
    referrer_name = None
    if referral.owner:
        referrer_name = referral.owner.display_name or referral.owner.email

    return ValidateCodeResponse(valid=True, referrer_name=referrer_name)


# ─────────────────────────────────────────────────────────────────────────────
# Authenticated Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/codes", response_model=ReferralCodesListResponse)
async def get_referral_codes(
    db: DbSession,
    current_user: CurrentUser,
) -> ReferralCodesListResponse:
    """
    Get user's referral codes and stats.

    Returns all codes owned by the user, plus statistics about
    remaining invites and conversion rates.
    """
    codes = await referral_ops.get_user_codes(db, current_user.id)
    stats = await referral_ops.get_referral_stats(db, current_user.id)

    # Convert to response models
    code_responses = []
    for code in codes:
        redeemed_by_name = None
        if code.redeemed_by:
            redeemed_by_name = code.redeemed_by.display_name or code.redeemed_by.email

        code_responses.append(
            ReferralCodeResponse(
                id=str(code.id),
                code=code.code,
                status=code.status,
                created_at=code.created_at,
                redeemed_at=code.redeemed_at,
                redeemed_by_name=redeemed_by_name,
                converted_at=code.converted_at,
            )
        )

    return ReferralCodesListResponse(
        codes=code_responses,
        stats=ReferralStatsResponse(**stats),
    )


@router.get("/stats", response_model=ReferralStatsResponse)
async def get_referral_stats(
    db: DbSession,
    current_user: CurrentUser,
) -> ReferralStatsResponse:
    """
    Get user's referral statistics.

    Lightweight endpoint that returns just the stats without all code details.
    """
    stats = await referral_ops.get_referral_stats(db, current_user.id)
    return ReferralStatsResponse(**stats)


@router.post("/codes", response_model=ReferralCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_referral_code(
    db: DbSession,
    current_user: CurrentUser,
) -> ReferralCodeResponse:
    """
    Generate a new referral code.

    Creates a new referral code if user has remaining capacity.
    Returns 403 if user has no remaining invites.
    """
    try:
        referral = await referral_ops.create_code(db, current_user.id)
        await db.commit()

        logger.info(f"Created referral code {referral.code} for user {current_user.id}")

        return ReferralCodeResponse(
            id=str(referral.id),
            code=referral.code,
            status=referral.status,
            created_at=referral.created_at,
            redeemed_at=None,
            redeemed_by_name=None,
            converted_at=None,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from None


@router.post("/redeem", response_model=RedeemCodeResponse)
async def redeem_referral_code(
    request: RedeemCodeRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> RedeemCodeResponse:
    """
    Redeem a referral code.

    Called during/after sign-up to associate a referral code with the new user.
    The recipient gets 1 free month immediately.
    The sender gets 1 free month when the recipient adds payment (conversion).

    Validates that:
    - Code exists and is available
    - User isn't redeeming their own code
    - User hasn't already redeemed a code
    """
    try:
        referral = await referral_ops.redeem_code(db, request.code, current_user.id)
        await db.commit()

        # Get referrer's name
        referrer_name = None
        if referral.owner:
            referrer_name = referral.owner.display_name or referral.owner.email

        logger.info(
            f"User {current_user.id} redeemed referral code {request.code} "
            f"from user {referral.user_id}"
        )

        return RedeemCodeResponse(
            success=True,
            message="Referral code redeemed! Your free month will be applied.",
            referrer_name=referrer_name,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None


# ─────────────────────────────────────────────────────────────────────────────
# URL Generation Helper
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/link/{code}")
async def get_referral_link(
    code: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, str]:
    """
    Get the full referral link for a code.

    Validates that the code belongs to the current user.
    Returns the public URL that can be shared.
    """
    referral = await referral_ops.get_by_code(db, code)

    if not referral:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referral code not found",
        )

    if referral.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not your referral code",
        )

    # Generate the public referral link
    base_url = settings.frontend_url.rstrip("/")
    referral_link = f"{base_url}/invite/{code}"

    return {
        "code": code,
        "link": referral_link,
        "status": referral.status,
    }
