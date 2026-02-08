"""Progress API: AI Summary endpoints."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ProductAccessContext,
    get_current_user,
    get_db_with_rls,
    get_product_access,
)
from app.models import User

from .commit_fetcher import fetch_commit_stats, fetch_product_commits
from .summary import _compute_summary

router = APIRouter()


@router.get("/products/{product_id}/ai-summary")
async def get_ai_summary(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get existing AI-generated summary for a product and period.

    Returns the stored summary if it exists, or {summary: null} if none.
    Does NOT generate a new summary - use POST /ai-summary/generate for that.
    """
    from app.domain import progress_summary_ops

    # Fetch existing summary
    summary = await progress_summary_ops.get_by_product_period(db, product_id, period)

    if summary:
        return {
            "summary": {
                "id": str(summary.id),
                "period": summary.period,
                "summary_text": summary.summary_text,
                "total_commits": summary.total_commits,
                "total_contributors": summary.total_contributors,
                "total_additions": summary.total_additions,
                "total_deletions": summary.total_deletions,
                "generated_at": summary.generated_at.isoformat(),
                "last_activity_at": (
                    summary.last_activity_at.isoformat() if summary.last_activity_at else None
                ),
            }
        }

    return {"summary": None}


@router.post("/products/{product_id}/ai-summary/generate")
async def generate_ai_summary(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Generate a new AI summary for a product's development progress.

    Fetches current progress data, generates a narrative summary using Claude,
    stores it in the database, and returns the result.

    This is a synchronous operation (typically 2-5 seconds) since Claude
    responses are fast enough that polling adds unnecessary complexity.
    """
    from app.domain import progress_summary_ops
    from app.services.progress.summarizer import ProgressData, progress_summarizer

    # Fetch commits using consolidated fetcher
    result = await fetch_product_commits(
        db=db,
        product_id=product_id,
        current_user=current_user,
        period=period,
        repo_ids=repo_ids,
        fetch_limit=200,
    )

    if not result:
        raise HTTPException(
            status_code=400,
            detail="No commits found in the selected period. Cannot generate summary.",
        )

    # Fetch commit stats for LOC calculation
    events = await fetch_commit_stats(db, result.github, result.repos, result.events)

    # Compute summary data (reuse existing function)
    summary_data = _compute_summary(events, period)

    # Build ProgressData for the AI summarizer
    progress_data = ProgressData(
        period=period,
        total_commits=summary_data["total_commits"],
        total_contributors=summary_data["total_contributors"],
        total_additions=summary_data["total_additions"],
        total_deletions=summary_data["total_deletions"],
        focus_areas=summary_data["focus_areas"],
        top_contributors=summary_data["top_contributors"],
        recent_commits=summary_data["recent_commits"],
    )

    # Generate AI narrative
    try:
        narrative = await progress_summarizer.interpret(progress_data)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary: {str(e)}",
        ) from e

    # Store the summary (set last_activity_at to now to reset staleness clock)
    now = datetime.now(UTC)
    stored_summary = await progress_summary_ops.upsert(
        db=db,
        product_id=product_id,
        period=period,
        summary_text=narrative.summary,
        total_commits=summary_data["total_commits"],
        total_contributors=summary_data["total_contributors"],
        total_additions=summary_data["total_additions"],
        total_deletions=summary_data["total_deletions"],
        last_activity_at=now,
    )

    await db.commit()

    return {
        "summary": {
            "id": str(stored_summary.id),
            "period": stored_summary.period,
            "summary_text": stored_summary.summary_text,
            "total_commits": stored_summary.total_commits,
            "total_contributors": stored_summary.total_contributors,
            "total_additions": stored_summary.total_additions,
            "total_deletions": stored_summary.total_deletions,
            "generated_at": stored_summary.generated_at.isoformat(),
            "last_activity_at": (
                stored_summary.last_activity_at.isoformat()
                if stored_summary.last_activity_at
                else None
            ),
        }
    }
