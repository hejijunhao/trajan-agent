"""
Analysis Orchestrator service for coordinating the complete analysis workflow.

This service coordinates all extraction tasks:
1. Fetch repo contexts (parallel per repo)
2. Extract stats (no LLM) - StatsExtractor
3. Extract architecture (Sonnet) - ArchitectureExtractor
4. Generate content (Sonnet) - ContentGenerator
5. Merge into ProductOverview

Part of the Analysis Agent refactoring (Phase 5).
"""

import asyncio
import logging
import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.repository_operations import repository_ops
from app.models.product import Product
from app.models.repository import Repository
from app.schemas.analysis_progress import AnalysisProgress
from app.schemas.product_overview import (
    OverviewArchitecture,
    OverviewStats,
    OverviewSummary,
    ProductOverview,
)
from app.services.architecture_extractor import ArchitectureExtractor
from app.services.content_generator import ContentGenerator, ContentResult
from app.services.github import GitHubService, RepoContext
from app.services.stats_extractor import StatsExtractor

logger = logging.getLogger(__name__)

# Model name for tracking in ProductOverview
ORCHESTRATOR_MODEL = "claude-sonnet-4-20250514"


class AnalysisOrchestrator:
    """
    Orchestrates the complete analysis workflow.

    This class coordinates all the individual extractors and generators
    to produce a complete ProductOverview. It manages:
    - Progress updates for frontend polling
    - Parallel execution where possible
    - Error handling and graceful degradation
    """

    def __init__(
        self,
        session: AsyncSession,
        github_token: str,
        product: Product,
    ) -> None:
        """
        Initialize the orchestrator.

        Args:
            session: Database session for querying repositories and updating progress
            github_token: GitHub Personal Access Token for API access
            product: The product being analyzed (for progress updates)
        """
        self.session = session
        self.product = product
        self.github = GitHubService(github_token)
        self.stats_extractor = StatsExtractor()
        self.arch_extractor = ArchitectureExtractor()
        self.content_generator = ContentGenerator()

    async def analyze_product(self, user_id: uuid_pkg.UUID) -> ProductOverview:
        """
        Full analysis workflow with parallel execution.

        Workflow:
        1. Fetch repository contexts from GitHub (parallel per repo)
        2. Run stats extraction + architecture extraction in parallel
        3. Generate content (depends on stats + architecture)
        4. Merge everything into ProductOverview

        Args:
            user_id: The user's ID (for data isolation)

        Returns:
            ProductOverview with complete analysis results
        """
        product = self.product
        logger.info(f"Starting orchestrated analysis for product: {product.name} (id={product.id})")

        # Stage 1: Fetching repository data
        await self._update_progress(
            AnalysisProgress(
                stage="fetching_repos",
                stage_number=1,
                message="Connecting to GitHub...",
            )
        )

        repos = await self._get_github_repos(product.id, user_id)
        if not repos:
            logger.warning(f"No GitHub repositories found for product {product.id}")
            return self._create_empty_overview(product)

        logger.info(f"Found {len(repos)} GitHub repositories to analyze")

        # Stage 2: Scanning file structure (fetch all repo contexts)
        await self._update_progress(
            AnalysisProgress(
                stage="scanning_files",
                stage_number=2,
                message=f"Scanning {len(repos)} repositories...",
            )
        )

        repo_contexts = await self._fetch_all_contexts(repos)

        if not repo_contexts:
            logger.error("Failed to fetch context from any repositories")
            return self._create_empty_overview(product)

        # Stage 3: Analyzing code structure (stats + architecture in parallel)
        await self._update_progress(
            AnalysisProgress(
                stage="analyzing_code",
                stage_number=3,
                message="Extracting statistics and architecture...",
            )
        )

        # Run stats and architecture extraction in parallel (independent tasks)
        stats, architecture = await self._extract_in_parallel(repo_contexts)

        logger.info(
            f"Extracted stats: {stats.total_files} files, {stats.stars} stars | "
            f"Architecture: {len(architecture.api_endpoints)} endpoints, "
            f"{len(architecture.database_models)} models"
        )

        # Stage 4: Generating content (depends on stats + architecture)
        await self._update_progress(
            AnalysisProgress(
                stage="generating_content",
                stage_number=4,
                message="Writing project documentation...",
            )
        )

        content = await self.content_generator.generate_content(
            product, repo_contexts, stats, architecture
        )

        # Build final ProductOverview
        overview = self._build_overview(content, stats, architecture)

        logger.info(f"Analysis orchestration complete for product: {product.name}")
        return overview

    async def _get_github_repos(
        self,
        product_id: uuid_pkg.UUID | None,
        user_id: uuid_pkg.UUID,
    ) -> list[Repository]:
        """Fetch all GitHub-linked repositories for a product."""
        if product_id is None:
            return []
        return await repository_ops.get_github_repos_by_product(
            self.session,
            user_id,
            product_id,
        )

    async def _fetch_all_contexts(self, repos: list[Repository]) -> list[RepoContext]:
        """
        Fetch contexts for all repositories with progress updates.

        Fetches are done sequentially to avoid overwhelming GitHub API,
        but each repo's internal file fetches run in parallel.
        """
        repo_contexts: list[RepoContext] = []

        for i, repo in enumerate(repos):
            try:
                # Update progress with current repo
                await self._update_progress(
                    AnalysisProgress(
                        stage="scanning_files",
                        stage_number=2,
                        current_repo=repo.full_name,
                        message=f"Scanning repository {i + 1} of {len(repos)}...",
                    )
                )

                context = await self._fetch_repo_context(repo)
                repo_contexts.append(context)
                logger.info(
                    f"Fetched context for {repo.full_name}: "
                    f"{len(context.files)} files, {context.stars_count} stars"
                )
            except Exception as e:
                logger.error(f"Failed to fetch context for {repo.full_name}: {e}")
                # Continue with other repos

        return repo_contexts

    async def _fetch_repo_context(self, repo: Repository) -> RepoContext:
        """Fetch complete context for a single repository."""
        if not repo.full_name:
            raise ValueError(f"Repository {repo.name} has no full_name")

        owner, repo_name = repo.full_name.split("/", 1)

        return await self.github.get_repo_context(
            owner=owner,
            repo=repo_name,
            branch=repo.default_branch,
            description=repo.description,
        )

    async def _extract_in_parallel(
        self,
        repo_contexts: list[RepoContext],
    ) -> tuple["OverviewStats", "OverviewArchitecture"]:
        """
        Run stats and architecture extraction in parallel.

        These are independent tasks that don't depend on each other,
        so running them concurrently reduces total analysis time.

        Returns:
            Tuple of (OverviewStats, OverviewArchitecture)
        """
        # Create tasks for parallel execution
        stats_task = asyncio.create_task(
            asyncio.to_thread(self.stats_extractor.extract_stats, repo_contexts)
        )
        arch_task = asyncio.create_task(
            self.arch_extractor.extract_architecture(repo_contexts)
        )

        # Wait for both to complete
        stats, architecture = await asyncio.gather(stats_task, arch_task)

        return stats, architecture

    def _build_overview(
        self,
        content: "ContentResult",
        stats: "OverviewStats",
        architecture: "OverviewArchitecture",
    ) -> ProductOverview:
        """
        Merge all extracted data into final ProductOverview.

        Combines:
        - Content from ContentGenerator (prose fields)
        - Stats from StatsExtractor (metrics)
        - Architecture from ArchitectureExtractor (structure)
        """
        # Build summary from content
        summary = OverviewSummary(
            one_liner=content.one_liner,
            introduction=content.introduction,
            status=content.status,
        )

        return ProductOverview(
            summary=summary,
            stats=stats,
            technical_content=content.technical_content,
            business_content=content.business_content,
            features_content=content.features_content,
            use_cases_content=content.use_cases_content,
            architecture=architecture,
            analyzed_at=datetime.now(UTC),
            analyzer_model=ORCHESTRATOR_MODEL,
        )

    async def _update_progress(self, progress: AnalysisProgress) -> None:
        """Persist progress to database for frontend polling."""
        self.product.analysis_progress = progress.model_dump()
        self.session.add(self.product)
        await self.session.commit()
        await self.session.refresh(self.product)

    def _create_empty_overview(self, product: Product) -> ProductOverview:
        """Create an empty overview when no repositories are available."""
        return ProductOverview(
            summary=OverviewSummary(
                one_liner=f"{product.name} - No repositories linked for analysis",
                introduction=(
                    "This project has no GitHub repositories linked yet. "
                    "Add repositories to enable AI-powered analysis."
                ),
                status="active",
            ),
            stats=OverviewStats(),
            technical_content="No technical analysis available - no repositories linked.",
            business_content="No business analysis available - no repositories linked.",
            features_content="No features analysis available - no repositories linked.",
            use_cases_content="No use cases analysis available - no repositories linked.",
            architecture=OverviewArchitecture(),
            analyzed_at=datetime.now(UTC),
            analyzer_model=ORCHESTRATOR_MODEL,
        )
