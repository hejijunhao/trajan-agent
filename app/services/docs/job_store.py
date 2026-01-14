"""
Database-backed job store for custom document generation.

This provides persistent storage for tracking the progress of custom doc
generation jobs. Works across multiple workers/processes.

Jobs are stored in the database with automatic TTL cleanup.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_doc_job import CustomDocJob, JobStatus

logger = logging.getLogger(__name__)

# Job TTL (1 hour)
JOB_TTL_SECONDS = 3600

# Progress stages
STAGE_ANALYZING = "Analyzing codebase..."
STAGE_PLANNING = "Planning document structure..."
STAGE_GENERATING = "Generating content..."
STAGE_FINALIZING = "Finalizing document..."


async def create_job(db: AsyncSession, product_id: str, user_id: str) -> str:
    """Create a new job and return its ID."""
    expires_at = datetime.now(UTC) + timedelta(seconds=JOB_TTL_SECONDS)

    job = CustomDocJob(
        product_id=uuid.UUID(product_id),
        user_id=uuid.UUID(user_id),
        status=JobStatus.GENERATING.value,
        progress=STAGE_ANALYZING,
        expires_at=expires_at,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    logger.info(f"Created custom doc job: {job.id}")
    return str(job.id)


async def get_job(db: AsyncSession, job_id: str) -> CustomDocJob | None:
    """Get job by ID."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        return None

    result = await db.execute(
        select(CustomDocJob).where(CustomDocJob.id == job_uuid)  # type: ignore[arg-type]
    )
    return result.scalar_one_or_none()


async def update_progress(db: AsyncSession, job_id: str, progress: str) -> None:
    """Update the progress message for a job."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        return

    await db.execute(
        update(CustomDocJob)
        .where(CustomDocJob.id == job_uuid)  # type: ignore[arg-type]
        .values(progress=progress)
    )
    await db.commit()
    logger.debug(f"Job {job_id} progress: {progress}")


async def set_completed(
    db: AsyncSession,
    job_id: str,
    content: str,
    suggested_title: str,
) -> None:
    """Mark a job as completed with its result."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        return

    await db.execute(
        update(CustomDocJob)
        .where(CustomDocJob.id == job_uuid)  # type: ignore[arg-type]
        .values(
            status=JobStatus.COMPLETED.value,
            progress="Complete",
            content=content,
            suggested_title=suggested_title,
        )
    )
    await db.commit()
    logger.info(f"Job {job_id} completed")


async def set_failed(db: AsyncSession, job_id: str, error: str) -> None:
    """Mark a job as failed with an error message."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        return

    # Sanitize error message for users
    sanitized_error = _sanitize_error(error)

    await db.execute(
        update(CustomDocJob)
        .where(CustomDocJob.id == job_uuid)  # type: ignore[arg-type]
        .values(
            status=JobStatus.FAILED.value,
            error=sanitized_error,
        )
    )
    await db.commit()
    logger.error(f"Job {job_id} failed: {error}")


async def set_cancelled(db: AsyncSession, job_id: str) -> bool:
    """
    Mark a job as cancelled.

    Returns True if the job was found and cancelled, False otherwise.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        return False

    result = await db.execute(
        update(CustomDocJob)
        .where(CustomDocJob.id == job_uuid)  # type: ignore[arg-type]
        .where(CustomDocJob.status == JobStatus.GENERATING.value)  # type: ignore[arg-type]
        .values(status=JobStatus.CANCELLED.value)
    )
    await db.commit()

    cursor_result = cast(CursorResult[tuple[()]], result)
    if cursor_result.rowcount > 0:
        logger.info(f"Job {job_id} cancelled")
        return True
    return False


async def is_cancelled(db: AsyncSession, job_id: str) -> bool:
    """Check if a job has been cancelled."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        return False

    result = await db.execute(
        select(CustomDocJob).where(CustomDocJob.id == job_uuid)  # type: ignore[arg-type]
    )
    job = result.scalar_one_or_none()
    return job is not None and job.status == JobStatus.CANCELLED.value


async def cleanup_expired_jobs(db: AsyncSession) -> int:
    """Remove jobs older than TTL. Returns number of jobs cleaned up."""
    now = datetime.now(UTC)
    result = await db.execute(
        delete(CustomDocJob).where(CustomDocJob.expires_at < now)  # type: ignore[arg-type]
    )
    await db.commit()

    cursor_result = cast(CursorResult[tuple[()]], result)
    if cursor_result.rowcount > 0:
        logger.info(f"Cleaned up {cursor_result.rowcount} expired jobs")
    return cursor_result.rowcount


def _sanitize_error(error: str) -> str:
    """
    Sanitize error message for user display.

    Converts technical API errors into user-friendly messages.
    """
    error_lower = error.lower()

    if "ratelimit" in error_lower or "rate limit" in error_lower:
        return "Service is busy. Please try again in a few minutes."
    if "apierror" in error_lower or "api error" in error_lower:
        return "Failed to generate document. Please try again."
    if "timeout" in error_lower:
        return "Request timed out. Please try again."
    if "anthropic" in error_lower:
        return "Failed to generate document. Please try again."

    # If error is already short and clean, return it
    if len(error) < 100 and not any(char in error for char in ["<", ">", "{", "}"]):
        return error

    return "An unexpected error occurred. Please try again."
