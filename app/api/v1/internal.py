"""Internal API endpoints — protected by shared secret, not user auth.

These endpoints are called by cron jobs / external schedulers, not by
human users. They bypass Supabase JWT auth and instead validate a
shared secret via the X-Cron-Secret header.
"""

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _verify_cron_secret(x_cron_secret: str = Header(...)) -> None:
    """Validate the X-Cron-Secret header against the configured secret."""
    if not settings.cron_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cron secret not configured",
        )
    if x_cron_secret != settings.cron_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid cron secret",
        )


@router.post("/auto-progress")
async def trigger_auto_progress(
    x_cron_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Trigger auto-progress generation for all eligible organizations.

    Protected by X-Cron-Secret header. Called by external cron (e.g. GitHub Actions).
    Processes all orgs with auto_progress_enabled=true, checks for new commits,
    and regenerates AI summaries where needed.
    """
    _verify_cron_secret(x_cron_secret)

    from app.services.progress.auto_generator import auto_progress_generator

    report = await auto_progress_generator.run_for_all_orgs(db)
    await db.commit()

    return asdict(report)
