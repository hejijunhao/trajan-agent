"""Product analysis: AI-powered repository analysis."""

import uuid as uuid_pkg
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SubscriptionContext,
    check_product_editor_access,
    get_current_user,
    get_db_with_rls,
    require_agent_enabled,
)
from app.domain import product_ops
from app.domain.preferences_operations import preferences_ops
from app.models.user import User
from app.schemas.product_overview import AnalyzeProductResponse
from app.services.analysis import run_analysis_task

router = APIRouter()

# Analysis frequency limits in hours
ANALYSIS_FREQUENCY_LIMITS = {
    "weekly": 7 * 24,  # 168 hours
    "daily": 24,  # 24 hours
    "realtime": 0,  # No limit
}


@router.post("/{product_id}/analyze", response_model=AnalyzeProductResponse)
async def analyze_product(
    product_id: uuid_pkg.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    sub_ctx: SubscriptionContext = Depends(require_agent_enabled),
    db: AsyncSession = Depends(get_db_with_rls),
) -> AnalyzeProductResponse:
    """
    Trigger AI analysis of the product's repositories.

    Requires Editor or Admin access to the product.

    Additional requirements:
    - Agent to be enabled for the organization (free tier must be within repo limit)
    - Analysis frequency must be respected (weekly for Observer, daily for Foundations)

    Analysis runs in the background. Poll GET /products/{id} for status updates.
    The `analysis_status` field will be:
    - "analyzing" while in progress
    - "completed" when done (product_overview will contain results)
    - "failed" if an error occurred
    """
    # Check product access first
    await check_product_editor_access(db, product_id, current_user.id)

    # Get product
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Check if already analyzing
    if product.analysis_status == "analyzing":
        return AnalyzeProductResponse(
            status="already_analyzing",
            message="Analysis already in progress. Poll GET /products/{id} for status.",
        )

    # Check analysis frequency limit
    frequency_limit_hours = ANALYSIS_FREQUENCY_LIMITS.get(sub_ctx.plan.analysis_frequency, 0)
    if frequency_limit_hours > 0 and product.analysis_status == "completed":
        # Use updated_at as a proxy for when analysis was completed
        # (set when status changes to "completed")
        last_analysis_time = product.updated_at
        if last_analysis_time:
            hours_since_last = (datetime.now(UTC) - last_analysis_time).total_seconds() / 3600
            if hours_since_last < frequency_limit_hours:
                hours_remaining = int(frequency_limit_hours - hours_since_last)
                frequency_display = (
                    "once per week"
                    if sub_ctx.plan.analysis_frequency == "weekly"
                    else "once per day"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Analysis limited to {frequency_display} on {sub_ctx.plan.display_name} plan. "
                    f"Next analysis available in {hours_remaining} hours.",
                )

    # Get user's GitHub token from preferences (check existence only - token fetched in background task)
    prefs = await preferences_ops.get_by_user_id(db, user_id=current_user.id)
    if not prefs or not preferences_ops.get_decrypted_token(prefs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token required for analysis. Configure it in Settings → General.",
        )

    # Update status to analyzing
    product.analysis_status = "analyzing"
    db.add(product)
    await db.commit()

    # Dispatch background task
    # Note: run_analysis_task creates its own database session since
    # FastAPI's request session is closed by the time background tasks run.
    # Security: GitHub token is fetched inside the task, not passed as param.
    background_tasks.add_task(
        run_analysis_task,
        product_id=str(product.id),
        user_id=str(current_user.id),
    )

    return AnalyzeProductResponse(
        status="analyzing",
        message="Analysis started. Poll GET /products/{id} for status updates.",
    )
