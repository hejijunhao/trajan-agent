"""Auto-progress orchestrator for daily AI summary generation.

Main entry point for the cron job. Iterates over all organizations with
auto_progress_enabled, checks for new activity, and regenerates summaries
only when new commits exist.
"""

import asyncio
import logging
import time
import uuid as uuid_pkg
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.services.github import GitHubReadOperations
from app.services.progress.activity_checker import activity_checker
from app.services.progress.token_resolver import token_resolver

logger = logging.getLogger(__name__)

# Safety caps
MAX_PRODUCTS_PER_ORG = 50
PRODUCT_TIMEOUT_SECONDS = 30
TOTAL_JOB_TIMEOUT_SECONDS = 600  # 10 minutes max


@dataclass
class AutoProgressReport:
    """Summary of an auto-progress run (for logging/monitoring)."""

    orgs_processed: int = 0
    products_regenerated: int = 0
    products_skipped: int = 0
    products_failed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class AutoProgressGenerator:
    """Orchestrator that runs auto-progress for all eligible organizations."""

    async def run_for_all_orgs(
        self,
        db: AsyncSession,
    ) -> AutoProgressReport:
        """
        Main entry point for the cron job.

        1. Find all orgs with auto_progress_enabled = true
        2. For each org, resolve a GitHub token and process products
        3. Return a report of what was generated/skipped
        """
        from app.domain import organization_ops

        start = time.monotonic()
        report = AutoProgressReport()

        orgs = await organization_ops.get_orgs_with_auto_progress(db)
        logger.info(f"[auto-progress] Found {len(orgs)} orgs with auto-progress enabled")

        try:
            async with asyncio.timeout(TOTAL_JOB_TIMEOUT_SECONDS):
                for org in orgs:
                    try:
                        github_token = await token_resolver.resolve_for_org(db, org.id)
                        if not github_token:
                            logger.warning(
                                f"[auto-progress] Org {org.id} ({org.name}): "
                                "no GitHub token available, skipping"
                            )
                            continue

                        await self._process_org(db, org.id, github_token, report)
                        report.orgs_processed += 1

                    except Exception as e:
                        error_msg = f"Org {org.id} ({org.name}): {e}"
                        logger.error(f"[auto-progress] {error_msg}")
                        report.errors.append(error_msg)
        except TimeoutError:
            error_msg = f"Total job timeout ({TOTAL_JOB_TIMEOUT_SECONDS}s) exceeded"
            logger.error(f"[auto-progress] {error_msg}")
            report.errors.append(error_msg)

        report.duration_seconds = round(time.monotonic() - start, 2)

        logger.info(
            f"[auto-progress] Completed: {report.orgs_processed} orgs, "
            f"{report.products_regenerated} regenerated, "
            f"{report.products_skipped} skipped, "
            f"{report.products_failed} failed "
            f"({report.duration_seconds}s)"
        )

        return report

    async def _process_org(
        self,
        db: AsyncSession,
        org_id: uuid_pkg.UUID,
        github_token: str,
        report: AutoProgressReport,
    ) -> None:
        """Process all products in an organization."""
        from app.domain import product_ops, repository_ops

        products = await product_ops.get_by_organization(db, org_id)
        products = products[:MAX_PRODUCTS_PER_ORG]

        github = GitHubReadOperations(github_token)

        for product in products:
            try:
                async with asyncio.timeout(PRODUCT_TIMEOUT_SECONDS):
                    repos = await repository_ops.get_github_repos_by_product(db, product.id)
                    if not repos:
                        report.products_skipped += 1
                        continue

                    regenerated = await self._process_product(db, product, repos, github)
                    if regenerated:
                        report.products_regenerated += 1
                    else:
                        report.products_skipped += 1

            except TimeoutError:
                error_msg = (
                    f"Product {product.id} ({product.name}): "
                    f"timeout ({PRODUCT_TIMEOUT_SECONDS}s)"
                )
                logger.error(f"[auto-progress] {error_msg}")
                report.errors.append(error_msg)
                report.products_failed += 1
            except Exception as e:
                error_msg = f"Product {product.id} ({product.name}): {e}"
                logger.error(f"[auto-progress] {error_msg}")
                report.errors.append(error_msg)
                report.products_failed += 1

    async def _process_product(
        self,
        db: AsyncSession,
        product: Product,
        repos: list,
        github: GitHubReadOperations,
    ) -> bool:
        """
        Process a single product.

        1. Check latest commit date via ActivityChecker
        2. Compare with stored last_activity_at
        3. If newer commits exist → regenerate both summaries
        4. If no new commits → skip (return False)

        Returns True if summaries were regenerated, False if skipped.
        """
        from app.domain import (
            dashboard_shipped_ops,
            progress_summary_ops,
        )
        from app.services.progress.shipped_summarizer import (
            CommitInfo,
            ShippedAnalysisInput,
            shipped_summarizer,
        )
        from app.services.progress.summarizer import ProgressData, progress_summarizer

        # Default periods for auto-generation
        progress_period = "7d"
        dashboard_period = "7d"

        # 1. Check latest commit date (lightweight — per_page=1 per repo)
        latest_commit_date = await activity_checker.get_latest_commit_date(repos, github)

        if latest_commit_date is None:
            logger.debug(f"[auto-progress] Product {product.id}: no commits found")
            return False

        # 2. Compare with stored last_activity_at
        existing = await progress_summary_ops.get_by_product_period(db, product.id, progress_period)

        if (
            existing
            and existing.last_activity_at
            and latest_commit_date <= existing.last_activity_at
        ):
            logger.debug(f"[auto-progress] Product {product.id}: no new activity, skipping")
            return False

        # 3. New activity detected — regenerate summaries
        logger.info(
            f"[auto-progress] Product {product.id} ({product.name}): "
            "new activity detected, regenerating"
        )

        # Fetch commits for the period
        period_start = _get_period_start(progress_period)
        since_str = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")

        all_commits_raw: list[dict] = []
        for repo in repos:
            if not repo.full_name:
                continue
            try:
                owner, name = repo.full_name.split("/")
                commits, _ = await github.get_commits_for_timeline(
                    owner, name, repo.default_branch, per_page=200
                )
                for c in commits:
                    if c["commit"]["committer"]["date"] >= since_str:
                        all_commits_raw.append(c)
            except Exception as e:
                logger.warning(f"[auto-progress] Failed to fetch commits for {repo.full_name}: {e}")

        if not all_commits_raw:
            # Update last_activity_at even if no commits in period
            await progress_summary_ops.update_last_activity(
                db, product.id, progress_period, latest_commit_date
            )
            await dashboard_shipped_ops.update_last_activity(
                db, product.id, dashboard_period, latest_commit_date
            )
            await db.flush()
            return False

        # --- Generate Progress AI Summary ---
        try:
            # Build stats for the summarizer
            contributors: set[str] = set()
            for c in all_commits_raw:
                contributors.add(c["commit"]["author"]["name"])

            recent_commits_data = []
            for c in all_commits_raw[:10]:
                msg = c["commit"]["message"].split("\n")[0][:100]
                author = c["commit"]["author"]["name"]
                recent_commits_data.append({"message": msg, "author": author})

            progress_data = ProgressData(
                period=progress_period,
                total_commits=len(all_commits_raw),
                total_contributors=len(contributors),
                total_additions=0,
                total_deletions=0,
                focus_areas=[],
                top_contributors=[{"author": a, "commits": 0} for a in list(contributors)[:5]],
                recent_commits=recent_commits_data,
            )

            narrative = await progress_summarizer.interpret(progress_data)

            await progress_summary_ops.upsert(
                db=db,
                product_id=product.id,
                period=progress_period,
                summary_text=narrative.summary,
                total_commits=len(all_commits_raw),
                total_contributors=len(contributors),
                last_activity_at=latest_commit_date,
            )

        except Exception as e:
            logger.error(f"[auto-progress] Progress summary failed for {product.id}: {e}")

        # --- Generate Dashboard Shipped Summary ---
        try:
            commit_infos = [
                CommitInfo(
                    sha=c["sha"],
                    message=c["commit"]["message"].split("\n")[0][:200],
                    author=c["commit"]["author"]["name"],
                    timestamp=c["commit"]["committer"]["date"],
                    files=[],
                )
                for c in all_commits_raw
            ]

            input_data = ShippedAnalysisInput(
                product_id=product.id,
                product_name=product.name or "Unnamed",
                period=dashboard_period,
                commits=commit_infos,
            )
            summary = await shipped_summarizer.interpret(input_data)

            items_as_dicts = [
                {"description": item.description, "category": item.category}
                for item in summary.items
            ]
            await dashboard_shipped_ops.upsert(
                db=db,
                product_id=product.id,
                period=dashboard_period,
                items=items_as_dicts,
                has_significant_changes=summary.has_significant_changes,
                total_commits=len(all_commits_raw),
                last_activity_at=latest_commit_date,
            )

        except Exception as e:
            logger.error(f"[auto-progress] Shipped summary failed for {product.id}: {e}")

        await db.flush()
        return True


def _get_period_start(period: str) -> datetime:
    """Convert period string to start datetime (duplicated from progress.py to avoid circular)."""
    from datetime import timedelta

    now = datetime.now(UTC)
    period_map = {
        "24h": timedelta(hours=24),
        "48h": timedelta(hours=48),
        "7d": timedelta(days=7),
        "14d": timedelta(days=14),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "365d": timedelta(days=365),
    }
    delta = period_map.get(period, timedelta(days=7))
    return now - delta


auto_progress_generator = AutoProgressGenerator()
