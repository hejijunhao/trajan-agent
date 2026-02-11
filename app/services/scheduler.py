"""Internal task scheduler using APScheduler.

Runs scheduled jobs (like auto-progress) within the FastAPI process.
Uses PostgreSQL advisory locks to prevent duplicate execution when
multiple instances are running (e.g., Fly.io auto-scaling).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from app.config import settings
from app.core.database import async_session_maker

logger = logging.getLogger(__name__)

# Advisory lock IDs (arbitrary unique integers — one per job)
AUTO_PROGRESS_LOCK_ID = 891247
PLAN_PROMPT_LOCK_ID = 891248
WEEKLY_DIGEST_LOCK_ID = 891249


@asynccontextmanager
async def advisory_lock(lock_id: int) -> AsyncIterator[bool]:
    """
    Acquire a PostgreSQL advisory lock for the duration of the context.

    Advisory locks are session-level and automatically released when the
    session ends. We use pg_try_advisory_lock() which returns immediately
    (non-blocking) — if the lock is held by another process, we skip.
    """
    async with async_session_maker() as session:
        result = await session.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lock_id},
        )
        acquired = result.scalar()

        if not acquired:
            yield False
            return

        try:
            yield True
        finally:
            await session.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": lock_id},
            )
            await session.commit()


async def run_auto_progress() -> dict[str, Any] | None:
    """
    Execute the auto-progress job with advisory lock protection.

    Returns the report dict if executed, None if skipped (lock held by another instance).
    """
    async with advisory_lock(AUTO_PROGRESS_LOCK_ID) as acquired:
        if not acquired:
            logger.info("[scheduler] Auto-progress: skipped (another instance is running)")
            return None

        logger.info("[scheduler] Auto-progress: starting")

        try:
            from dataclasses import asdict

            from app.core.database import async_session_maker
            from app.services.progress.auto_generator import auto_progress_generator

            async with async_session_maker() as db:
                report = await auto_progress_generator.run_for_all_orgs(db)
                await db.commit()

            logger.info(
                f"[scheduler] Auto-progress: completed "
                f"({report.products_regenerated} regenerated, "
                f"{report.products_skipped} skipped, "
                f"{report.duration_seconds}s)"
            )
            return asdict(report)

        except Exception as e:
            logger.exception(f"[scheduler] Auto-progress: failed with error: {e}")
            return None


async def run_plan_prompt_emails() -> dict[str, Any] | None:
    """
    Execute the plan-prompt email job with advisory lock protection.

    Returns the report dict if executed, None if skipped (lock held by another instance).
    """
    async with advisory_lock(PLAN_PROMPT_LOCK_ID) as acquired:
        if not acquired:
            logger.info("[scheduler] Plan-prompt: skipped (another instance is running)")
            return None

        logger.info("[scheduler] Plan-prompt: starting")

        try:
            from dataclasses import asdict

            from app.core.database import async_session_maker
            from app.services.email.plan_prompt import send_plan_selection_prompts

            async with async_session_maker() as db:
                report = await send_plan_selection_prompts(db)
                await db.commit()

            logger.info(
                f"[scheduler] Plan-prompt: completed "
                f"({report.orgs_emailed} orgs emailed, "
                f"{report.emails_sent} emails sent)"
            )
            return asdict(report)

        except Exception as e:
            logger.exception(f"[scheduler] Plan-prompt: failed with error: {e}")
            return None


async def run_weekly_digest() -> dict[str, Any] | None:
    """
    Execute the weekly digest email job with advisory lock protection.

    Returns the report dict if executed, None if skipped (lock held by another instance).
    """
    async with advisory_lock(WEEKLY_DIGEST_LOCK_ID) as acquired:
        if not acquired:
            logger.info("[scheduler] Weekly-digest: skipped (another instance is running)")
            return None

        logger.info("[scheduler] Weekly-digest: starting")

        try:
            from dataclasses import asdict

            from app.core.database import async_session_maker
            from app.services.email.weekly_digest import send_weekly_digests

            async with async_session_maker() as db:
                report = await send_weekly_digests(db)
                await db.commit()

            logger.info(
                f"[scheduler] Weekly-digest: completed "
                f"({report.users_emailed} emailed, "
                f"{report.emails_sent} emails sent, "
                f"{report.duration_seconds}s)"
            )
            return asdict(report)

        except Exception as e:
            logger.exception(f"[scheduler] Weekly-digest: failed with error: {e}")
            return None


class Scheduler:
    """Manages the APScheduler instance and job registration."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        """Start the scheduler and register jobs."""
        if not settings.scheduler_enabled:
            logger.info("[scheduler] Disabled via SCHEDULER_ENABLED=false")
            return

        self._scheduler = AsyncIOScheduler()

        # Auto-progress: daily at configured hour (UTC)
        self._scheduler.add_job(
            run_auto_progress,
            trigger=CronTrigger(hour=settings.auto_progress_hour, minute=0),
            id="auto_progress",
            name="Auto-Progress Daily Generation",
            replace_existing=True,
        )

        # Plan-prompt emails: daily at configured hour, offset by 30 min
        self._scheduler.add_job(
            run_plan_prompt_emails,
            trigger=CronTrigger(hour=settings.plan_prompt_email_hour, minute=30),
            id="plan_prompt_emails",
            name="Plan Selection Prompt Emails",
            replace_existing=True,
        )

        # Weekly digest: hourly check (per-user timezone filtering happens in the service)
        self._scheduler.add_job(
            run_weekly_digest,
            trigger=CronTrigger(minute=0),
            id="weekly_digest",
            name="Weekly Digest Emails",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            f"[scheduler] Started with auto-progress at "
            f"{settings.auto_progress_hour:02d}:00 UTC, "
            f"plan-prompt at {settings.plan_prompt_email_hour:02d}:30 UTC, "
            f"weekly-digest hourly (per-user timezone)"
        )

    def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("[scheduler] Stopped")

    async def trigger_now(self, job_id: str) -> dict[str, Any] | None:
        """
        Manually trigger a job immediately (for testing/debugging).

        Returns the job result or None if job not found.
        """
        if job_id == "auto_progress":
            return await run_auto_progress()
        if job_id == "plan_prompt_emails":
            return await run_plan_prompt_emails()
        if job_id == "weekly_digest":
            return await run_weekly_digest()
        return None


scheduler = Scheduler()
