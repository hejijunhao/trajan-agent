"""Progress API: Dashboard endpoints (cross-product aggregation)."""

import logging
import uuid as uuid_pkg
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.domain import repository_ops
from app.domain.preferences_operations import preferences_ops
from app.models import User
from app.services.github import GitHubReadOperations

from .types import ProductShippedSummary
from .utils import generate_daily_activity, get_period_start, resolve_github_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard_progress(
    organization_id: uuid_pkg.UUID | None = Query(None, description="Filter to specific org"),
    days: int = Query(7, description="Time range: 7, 14, or 30 days"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get aggregated progress stats + shipped summaries for the dashboard.

    Returns cross-product metrics:
    - Aggregate stats (commits, LOC, contributors) across all accessible products
    - Daily activity for sparkline
    - AI-generated "What Shipped" summaries per project

    If no cached summaries exist, returns is_generating=False and empty summaries.
    Use POST /dashboard/generate to trigger summary generation.
    """
    from app.domain import dashboard_shipped_ops, org_member_ops, product_ops

    # Convert days to period string
    period = f"{days}d"
    if period not in ("7d", "14d", "30d"):
        period = "7d"

    # Get user's organizations
    memberships = await org_member_ops.get_by_user(db, current_user.id)
    if not memberships:
        return _empty_dashboard_response()

    # Filter to specific org if requested
    if organization_id:
        memberships = [m for m in memberships if m.organization_id == organization_id]
        if not memberships:
            return _empty_dashboard_response()

    # Get all products across user's orgs
    all_products: list[tuple[Any, Any]] = []
    for membership in memberships:
        products = await product_ops.get_by_organization(db, membership.organization_id)
        for product in products:
            all_products.append((product, membership.organization_id))

    if not all_products:
        return _empty_dashboard_response()

    # Get product IDs for cache lookup
    product_ids = [p.id for p, _ in all_products]

    # Resolve GitHub token (current user first for fast path)
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    user_token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    user_github = GitHubReadOperations(user_token) if user_token else None

    # Aggregate stats across all products
    aggregate_stats: dict[str, Any] = {
        "total_commits": 0,
        "total_additions": 0,
        "total_deletions": 0,
        "unique_contributors": set(),
        "daily_activity": defaultdict(int),
    }

    period_start = get_period_start(period)
    since_str = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    for product, _ in all_products:
        repos = await repository_ops.get_github_repos_by_product(db, product.id)
        if not repos:
            continue

        # Per-product token fallback when current user has no token
        product_github = user_github
        if not product_github:
            fallback_token = await resolve_github_token(db, current_user, product.id)
            if not fallback_token:
                continue
            product_github = GitHubReadOperations(fallback_token)

        for repo in repos:
            if not repo.full_name:
                continue
            try:
                owner, name = repo.full_name.split("/")
                commits, _ = await product_github.get_commits_for_timeline(
                    owner, name, repo.default_branch, per_page=100
                )

                for commit in commits:
                    timestamp = commit["commit"]["committer"]["date"]
                    if timestamp < since_str:
                        continue

                    aggregate_stats["total_commits"] += 1
                    aggregate_stats["unique_contributors"].add(commit["commit"]["author"]["name"])

                    date = timestamp.split("T")[0]
                    aggregate_stats["daily_activity"][date] += 1

            except Exception as e:
                logger.warning(f"Failed to fetch commits for {repo.full_name}: {e}")

    # Get cached shipped summaries
    summaries = await dashboard_shipped_ops.get_by_products_period(db, product_ids, period)
    summary_map = {str(s.product_id): s for s in summaries}

    # Build response
    shipped_summaries: list[dict[str, Any]] = []
    for product, _ in all_products:
        cached = summary_map.get(str(product.id))
        if cached:
            shipped_summaries.append(
                asdict(
                    ProductShippedSummary(
                        product_id=str(product.id),
                        product_name=product.name or "Unnamed",
                        product_color=product.color,
                        items=cached.items,
                        has_significant_changes=cached.has_significant_changes,
                        total_commits=cached.total_commits,
                        total_additions=cached.total_additions,
                        total_deletions=cached.total_deletions,
                        generated_at=cached.generated_at.isoformat(),
                        last_activity_at=(
                            cached.last_activity_at.isoformat() if cached.last_activity_at else None
                        ),
                    )
                )
            )

    # Generate daily activity for sparkline
    daily_activity = generate_daily_activity(dict(aggregate_stats["daily_activity"]), period)

    return {
        "total_commits": aggregate_stats["total_commits"],
        "total_additions": aggregate_stats["total_additions"],
        "total_deletions": aggregate_stats["total_deletions"],
        "unique_contributors": len(aggregate_stats["unique_contributors"]),
        "daily_activity": daily_activity,
        "shipped_summaries": shipped_summaries,
        "generated_at": (
            max((s.generated_at for s in summaries), default=None).isoformat()
            if summaries
            else None
        ),
        "is_generating": False,
    }


@router.post("/dashboard/generate")
async def generate_dashboard_progress(
    organization_id: uuid_pkg.UUID | None = Query(None, description="Filter to specific org"),
    days: int = Query(7, description="Time range: 7, 14, or 30 days"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Generate shipped summaries for all accessible products.

    Fetches commits for each product and uses AI to generate "What Shipped"
    summaries. Results are cached for subsequent GET requests.
    """
    from app.domain import dashboard_shipped_ops, org_member_ops, product_ops
    from app.services.progress.shipped_summarizer import (
        CommitInfo,
        ShippedAnalysisInput,
        shipped_summarizer,
    )

    # Convert days to period string
    period = f"{days}d"
    if period not in ("7d", "14d", "30d"):
        period = "7d"

    # Get user's organizations
    memberships = await org_member_ops.get_by_user(db, current_user.id)
    if not memberships:
        raise HTTPException(status_code=400, detail="No organizations found")

    # Filter to specific org if requested
    if organization_id:
        memberships = [m for m in memberships if m.organization_id == organization_id]
        if not memberships:
            raise HTTPException(status_code=400, detail="Organization not found")

    # Get all products across user's orgs
    all_products: list[Any] = []
    for membership in memberships:
        products = await product_ops.get_by_organization(db, membership.organization_id)
        all_products.extend(products)

    if not all_products:
        raise HTTPException(status_code=400, detail="No products found")

    # Resolve GitHub token (current user first for fast path)
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    user_token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    github = GitHubReadOperations(user_token) if user_token else None

    period_start = get_period_start(period)
    since_str = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Process each product
    shipped_summaries: list[dict[str, Any]] = []
    aggregate_stats: dict[str, Any] = {
        "total_commits": 0,
        "total_additions": 0,
        "total_deletions": 0,
        "unique_contributors": set(),
        "daily_activity": defaultdict(int),
    }

    for product in all_products:
        repos = await repository_ops.get_github_repos_by_product(db, product.id)
        if not repos:
            continue

        # Per-product token fallback when current user has no token
        product_github = github
        if not product_github:
            fallback_token = await resolve_github_token(db, current_user, product.id)
            if not fallback_token:
                continue
            product_github = GitHubReadOperations(fallback_token)

        # Fetch commits for this product
        product_commits: list[CommitInfo] = []
        product_stats = {"commits": 0, "additions": 0, "deletions": 0}

        for repo in repos:
            if not repo.full_name:
                continue
            try:
                owner, name = repo.full_name.split("/")
                commits, _ = await product_github.get_commits_for_timeline(
                    owner, name, repo.default_branch, per_page=100
                )

                for commit in commits:
                    timestamp = commit["commit"]["committer"]["date"]
                    if timestamp < since_str:
                        continue

                    message = commit["commit"]["message"].split("\n")[0][:200]
                    product_commits.append(
                        CommitInfo(
                            sha=commit["sha"],
                            message=message,
                            author=commit["commit"]["author"]["name"],
                            timestamp=timestamp,
                            files=[],
                        )
                    )

                    product_stats["commits"] += 1
                    aggregate_stats["total_commits"] += 1
                    aggregate_stats["unique_contributors"].add(commit["commit"]["author"]["name"])

                    date = timestamp.split("T")[0]
                    aggregate_stats["daily_activity"][date] += 1

            except Exception as e:
                logger.warning(f"Failed to fetch commits for {repo.full_name}: {e}")

        # Generate AI summary for this product
        try:
            input_data = ShippedAnalysisInput(
                product_id=product.id,
                product_name=product.name or "Unnamed",
                period=period,
                commits=product_commits,
            )
            summary = await shipped_summarizer.interpret(input_data)

            items_as_dicts = [
                {"description": item.description, "category": item.category}
                for item in summary.items
            ]
            cached_summary = await dashboard_shipped_ops.upsert(
                db=db,
                product_id=product.id,
                period=period,
                items=items_as_dicts,
                has_significant_changes=summary.has_significant_changes,
                total_commits=product_stats["commits"],
                total_additions=product_stats["additions"],
                total_deletions=product_stats["deletions"],
            )

            shipped_summaries.append(
                asdict(
                    ProductShippedSummary(
                        product_id=str(product.id),
                        product_name=product.name or "Unnamed",
                        product_color=product.color,
                        items=items_as_dicts,
                        has_significant_changes=summary.has_significant_changes,
                        total_commits=product_stats["commits"],
                        total_additions=product_stats["additions"],
                        total_deletions=product_stats["deletions"],
                        generated_at=cached_summary.generated_at.isoformat(),
                        last_activity_at=(
                            cached_summary.last_activity_at.isoformat()
                            if cached_summary.last_activity_at
                            else None
                        ),
                    )
                )
            )

        except Exception as e:
            logger.error(f"Failed to generate summary for product {product.id}: {e}")

    await db.commit()

    daily_activity = generate_daily_activity(dict(aggregate_stats["daily_activity"]), period)

    return {
        "total_commits": aggregate_stats["total_commits"],
        "total_additions": aggregate_stats["total_additions"],
        "total_deletions": aggregate_stats["total_deletions"],
        "unique_contributors": len(aggregate_stats["unique_contributors"]),
        "daily_activity": daily_activity,
        "shipped_summaries": shipped_summaries,
        "generated_at": datetime.now(UTC).isoformat(),
        "is_generating": False,
    }


def _empty_dashboard_response() -> dict[str, Any]:
    """Return an empty dashboard response."""
    return {
        "total_commits": 0,
        "total_additions": 0,
        "total_deletions": 0,
        "unique_contributors": 0,
        "daily_activity": [],
        "shipped_summaries": [],
        "generated_at": None,
        "is_generating": False,
    }
