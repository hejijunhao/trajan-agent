"""Progress API endpoints package.

This package provides the Progress tab functionality including:
- Summary statistics
- Contributors breakdown
- AI-generated summaries
- Active code visualization
- Velocity charts
- Dashboard aggregation
"""

from fastapi import APIRouter

from .active_code import router as active_code_router
from .ai_summary import router as ai_summary_router
from .commit_fetcher import MAX_CONCURRENT_STAT_FETCHES
from .contributors import router as contributors_router
from .dashboard import router as dashboard_router
from .leaderboard import router as leaderboard_router
from .summary import router as summary_router
from .utils import (
    _handle_repo_rename,
    _resolve_github_token,
    get_period_start,
)
from .velocity import router as velocity_router

# Compose the main router
router = APIRouter(prefix="/progress", tags=["progress"])
router.include_router(summary_router)
router.include_router(contributors_router)
router.include_router(ai_summary_router)
router.include_router(active_code_router)
router.include_router(velocity_router)
router.include_router(leaderboard_router)
router.include_router(dashboard_router)

__all__ = [
    "router",
    "_resolve_github_token",
    "_handle_repo_rename",
    "get_period_start",
    "MAX_CONCURRENT_STAT_FETCHES",
]
