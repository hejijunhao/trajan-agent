"""
In-memory job store for custom document generation.

This provides ephemeral storage for tracking the progress of custom doc
generation jobs. Jobs are stored in memory and automatically cleaned up
after a TTL period.

For production with multiple workers, consider Redis or database storage.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import ClassVar

logger = logging.getLogger(__name__)

# Job TTL (1 hour)
JOB_TTL_SECONDS = 3600

# Progress stages
STAGE_ANALYZING = "Analyzing codebase..."
STAGE_PLANNING = "Planning document structure..."
STAGE_GENERATING = "Generating content..."
STAGE_FINALIZING = "Finalizing document..."


@dataclass
class CustomDocJobState:
    """State of an in-progress custom document generation job."""

    job_id: str
    product_id: str
    user_id: str
    status: str = "generating"  # "generating" | "completed" | "failed"
    progress: str = STAGE_ANALYZING
    content: str | None = None
    suggested_title: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)


class CustomDocJobStore:
    """
    In-memory store for custom document generation jobs.

    Thread-safe singleton that manages job state for background generation.
    Jobs are automatically cleaned up after TTL_SECONDS.
    """

    _instance: ClassVar["CustomDocJobStore | None"] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __new__(cls) -> "CustomDocJobStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._jobs: dict[str, CustomDocJobState] = {}
            cls._instance._cleanup_task: asyncio.Task[None] | None = None
        return cls._instance

    async def create_job(self, product_id: str, user_id: str) -> str:
        """Create a new job and return its ID."""
        job_id = str(uuid.uuid4())
        job = CustomDocJobState(
            job_id=job_id,
            product_id=product_id,
            user_id=user_id,
        )
        self._jobs[job_id] = job
        logger.info(f"Created custom doc job: {job_id}")

        # Start cleanup task if not running
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        return job_id

    async def get_job(self, job_id: str) -> CustomDocJobState | None:
        """Get job state by ID."""
        return self._jobs.get(job_id)

    async def update_progress(self, job_id: str, progress: str) -> None:
        """Update the progress message for a job."""
        if job_id in self._jobs:
            self._jobs[job_id].progress = progress
            logger.debug(f"Job {job_id} progress: {progress}")

    async def set_completed(
        self,
        job_id: str,
        content: str,
        suggested_title: str,
    ) -> None:
        """Mark a job as completed with its result."""
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = "completed"
            job.content = content
            job.suggested_title = suggested_title
            job.progress = "Complete"
            logger.info(f"Job {job_id} completed")

    async def set_failed(self, job_id: str, error: str) -> None:
        """Mark a job as failed with an error message."""
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.status = "failed"
            job.error = error
            logger.error(f"Job {job_id} failed: {error}")

    async def delete_job(self, job_id: str) -> None:
        """Delete a job from the store."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            logger.debug(f"Deleted job {job_id}")

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired jobs."""
        while True:
            await asyncio.sleep(300)  # Run every 5 minutes
            await self._cleanup_expired()

    async def _cleanup_expired(self) -> None:
        """Remove jobs older than TTL."""
        now = time.time()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if now - job.created_at > JOB_TTL_SECONDS
        ]
        for job_id in expired:
            del self._jobs[job_id]
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired jobs")


# Singleton accessor
def get_job_store() -> CustomDocJobStore:
    """Get the singleton job store instance."""
    return CustomDocJobStore()
