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
from app.services.file_selector import FileSelector, FileSelectorInput
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
        self.file_selector = FileSelector()

    async def analyze_product(self, user_id: uuid_pkg.UUID) -> ProductOverview:
        """
        Full analysis workflow with parallel execution.

        Workflow:
        1. Fetch repository contexts from GitHub (tree + key files)
        2. Identify architecturally significant files using AI
        3. Fetch selected files and update contexts
        4. Run stats extraction + architecture extraction in parallel
        5. Generate content (depends on stats + architecture)

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

        # Stage 2: Scanning file structure (fetch repo contexts without architecture files)
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

        # Stage 3: Identify key files using AI
        await self._update_progress(
            AnalysisProgress(
                stage="identifying_files",
                stage_number=3,
                message="Identifying key architecture files...",
            )
        )

        repo_contexts = await self._identify_and_fetch_files(repos, repo_contexts)

        # Stage 4: Analyzing code structure (stats + architecture in parallel)
        await self._update_progress(
            AnalysisProgress(
                stage="analyzing_code",
                stage_number=4,
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

        # Stage 5: Generating content (depends on stats + architecture)
        await self._update_progress(
            AnalysisProgress(
                stage="generating_content",
                stage_number=5,
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
        """Fetch context for a single repository (without architecture files).

        Architecture files are fetched separately after AI-based file selection.
        """
        if not repo.full_name:
            raise ValueError(f"Repository {repo.name} has no full_name")

        owner, repo_name = repo.full_name.split("/", 1)

        return await self.github.get_repo_context(
            owner=owner,
            repo=repo_name,
            branch=repo.default_branch,
            description=repo.description,
            skip_architecture_files=True,  # Files selected dynamically
        )

    async def _identify_and_fetch_files(
        self,
        repos: list[Repository],
        repo_contexts: list[RepoContext],
    ) -> list[RepoContext]:
        """
        Use AI to identify architecturally significant files and fetch them.

        For each repository:
        1. Send file tree to FileSelector (Claude Haiku)
        2. Get back list of significant files
        3. Fetch those files via GitHub API
        4. Update the RepoContext with the new files

        Args:
            repos: List of Repository models (for metadata)
            repo_contexts: List of RepoContext with tree but minimal files

        Returns:
            Updated list of RepoContext with architecture files added
        """
        updated_contexts: list[RepoContext] = []

        for repo, context in zip(repos, repo_contexts, strict=True):
            # Update progress with current repo
            await self._update_progress(
                AnalysisProgress(
                    stage="identifying_files",
                    stage_number=3,
                    current_repo=repo.full_name,
                    message=f"Identifying key files in {repo.full_name}...",
                )
            )

            # Skip if no tree available
            if not context.tree or not context.tree.files:
                logger.warning(f"No file tree for {context.full_name}, skipping file selection")
                updated_contexts.append(context)
                continue

            try:
                # Get README content from existing files for context
                readme_content = context.files.get("README.md") or context.files.get("readme.md")

                # Use FileSelector to identify significant files
                selector_input = FileSelectorInput(
                    repo_name=context.full_name,
                    description=context.description,
                    readme_content=readme_content,
                    file_paths=context.tree.files,
                )

                result = await self.file_selector.select_files(selector_input)

                if result.selected_files:
                    logger.info(
                        f"FileSelector identified {len(result.selected_files)} files for "
                        f"{context.full_name} (truncated: {result.truncated})"
                    )

                    # Fetch the selected files
                    owner, repo_name = context.full_name.split("/", 1)
                    selected_file_contents = await self.github.fetch_files_by_paths(
                        owner=owner,
                        repo=repo_name,
                        paths=result.selected_files,
                        branch=context.default_branch,
                    )

                    # Merge with existing files (key files + selected architecture files)
                    context.files.update(selected_file_contents)
                    logger.info(
                        f"Fetched {len(selected_file_contents)} files, "
                        f"total files now: {len(context.files)}"
                    )
                else:
                    logger.warning(f"FileSelector returned no files for {context.full_name}")

            except Exception as e:
                logger.error(f"Failed to select/fetch files for {context.full_name}: {e}")
                context.errors.append(f"Failed to identify architecture files: {e}")

            updated_contexts.append(context)

        return updated_contexts

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
        arch_task = asyncio.create_task(self.arch_extractor.extract_architecture(repo_contexts))

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
