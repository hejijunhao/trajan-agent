"""
DocumentOrchestrator - Coordinates the entire documentation generation process.

This is the top-level orchestrator that:
1. Scans repositories for existing documentation
2. Imports existing docs into our folder structure
3. Performs deep codebase analysis (v2)
4. Plans documentation using Claude Opus 4.5 (v2)
5. Generates documents sequentially from the plan (v2)
6. Coordinates progress updates for frontend polling

V2 Flow (default):
    Import existing → Analyze codebase → Plan docs → Generate sequentially

V1 Flow (legacy, use_v2=False):
    Import existing → ChangelogAgent → BlueprintAgent → PlansAgent
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.document_operations import document_ops
from app.domain.repository_operations import repository_ops
from app.models.document import Document
from app.models.product import Product
from app.models.repository import Repository
from app.services.docs.blueprint_agent import BlueprintAgent
from app.services.docs.changelog_agent import ChangelogAgent
from app.services.docs.codebase_analyzer import CodebaseAnalyzer
from app.services.docs.document_generator import DocumentGenerator
from app.services.docs.documentation_planner import DocumentationPlanner
from app.services.docs.plans_agent import PlansAgent
from app.services.docs.types import DocsInfo, OrchestratorResult
from app.services.docs.utils import extract_title, infer_doc_type, map_path_to_folder
from app.services.github import GitHubService
from app.services.github.types import RepoTreeItem

logger = logging.getLogger(__name__)

# Default token budget for codebase analysis
DEFAULT_ANALYSIS_TOKEN_BUDGET = 100_000


class DocumentOrchestrator:
    """
    Tier 1 orchestrator that coordinates documentation generation.

    Responsibilities:
    1. Check if repos have existing docs/ folders
    2. Scan and import existing documentation
    3. Analyze codebase deeply (v2)
    4. Plan documentation with Claude Opus 4.5 (v2)
    5. Generate documents sequentially (v2)
    6. Ensure all docs are structured into our opinionated folders
    """

    def __init__(
        self,
        db: AsyncSession,
        product: Product,
        github_service: GitHubService,
    ) -> None:
        self.db = db
        self.product = product
        self.github_service = github_service

        # V2 services
        self.codebase_analyzer = CodebaseAnalyzer(github_service)
        self.documentation_planner = DocumentationPlanner()
        self.document_generator = DocumentGenerator(db)

        # V1 sub-agents (legacy, used when use_v2=False)
        self.changelog_agent = ChangelogAgent(db, product, github_service)
        self.blueprint_agent = BlueprintAgent(db, product, github_service)
        self.plans_agent = PlansAgent(db, product, github_service)

    async def run(self, use_v2: bool = True) -> OrchestratorResult:
        """
        Main entry point for documentation generation.

        Args:
            use_v2: If True (default), use the v2 flow with deep analysis and planning.
                    If False, use the legacy v1 flow with BlueprintAgent.

        V2 Flow:
            1. Scan and import existing docs
            2. Deep codebase analysis (CodebaseAnalyzer)
            3. Plan documentation (DocumentationPlanner with Opus 4.5)
            4. Generate documents sequentially (DocumentGenerator)
            5. Organize plans

        V1 Flow (legacy):
            1. Scan and import existing docs
            2. ChangelogAgent
            3. BlueprintAgent (fixed Overview + Architecture)
            4. PlansAgent

        Returns:
            OrchestratorResult with all processing results
        """
        if use_v2:
            return await self._run_v2()
        else:
            return await self._run_v1()

    async def _run_v2(self) -> OrchestratorResult:
        """
        V2 flow: Deep analysis → Intelligent planning → Sequential generation.

        This is the new Documentation Agent v2 flow that uses Claude Opus 4.5
        for planning and generates documents based on actual codebase analysis.
        """
        results = OrchestratorResult()

        logger.info(f"Starting v2 documentation orchestration for product {self.product.id}")

        # Stage 1: Import existing docs
        await self._update_progress("importing", "Scanning repositories for documentation...")
        repos = await self._get_linked_repos()
        logger.info(f"Found {len(repos)} linked repositories")

        for repo in repos:
            if not repo.full_name:
                continue
            try:
                docs_info = await self._scan_repo_docs(repo)
                if docs_info.has_docs_folder and docs_info.has_markdown_files:
                    logger.info(f"Found {len(docs_info.files)} doc files in {repo.full_name}")
                    imported = await self._import_existing_docs(repo, docs_info)
                    results.imported.extend(imported)
            except Exception as e:
                logger.error(f"Failed to scan docs for {repo.full_name}: {e}")

        # Stage 2: Deep codebase analysis
        await self._update_progress("analyzing", "Analyzing codebase structure...")
        try:
            codebase_context = await self.codebase_analyzer.analyze(
                repos, token_budget=DEFAULT_ANALYSIS_TOKEN_BUDGET
            )
            logger.info(
                f"Codebase analysis complete: {codebase_context.total_files} files, "
                f"{codebase_context.total_tokens} tokens analyzed"
            )
        except Exception as e:
            logger.error(f"Codebase analysis failed: {e}")
            # Fall back to v1 if analysis fails
            await self._update_progress("error", f"Analysis failed: {e}")
            return await self._run_v1()

        # Stage 3: Documentation planning
        await self._update_progress("planning", "Creating documentation plan...")
        try:
            # Get existing docs to avoid duplication
            existing_docs = await self._get_existing_docs()

            planner_result = await self.documentation_planner.create_plan(
                codebase_context=codebase_context,
                existing_docs=existing_docs,
                mode="full",
            )

            if not planner_result.success:
                logger.error(f"Documentation planning failed: {planner_result.error}")
                await self._update_progress("error", f"Planning failed: {planner_result.error}")
                return await self._run_v1()

            plan = planner_result.plan
            logger.info(
                f"Documentation plan created: {len(plan.planned_documents)} documents to generate"
            )
        except Exception as e:
            logger.error(f"Documentation planning failed: {e}")
            return await self._run_v1()

        # Stage 4: Sequential document generation
        if plan.planned_documents:
            total_docs = len(plan.planned_documents)

            async def on_progress(current: int, total: int, title: str) -> None:
                await self._update_progress(
                    "generating",
                    f"Generating {title} ({current}/{total})...",
                )

            try:
                batch_result = await self.document_generator.generate_batch(
                    plan=plan,
                    codebase_context=codebase_context,
                    product=self.product,
                    user_id=self.product.user_id,
                    on_progress=on_progress,
                )

                results.blueprints.extend(batch_result.documents)
                logger.info(
                    f"Document generation complete: {batch_result.total_generated}/{total_docs} "
                    f"generated, {len(batch_result.failed)} failed"
                )

                if batch_result.failed:
                    logger.warning(f"Failed documents: {batch_result.failed}")

            except Exception as e:
                logger.error(f"Document generation failed: {e}")

        # Stage 5: Changelog (still use v1 agent for changelog)
        await self._update_progress("changelog", "Processing changelog...")
        try:
            changelog_result = await self.changelog_agent.run()
            results.changelog = changelog_result
            logger.info(f"Changelog result: {changelog_result.action}")
        except Exception as e:
            logger.error(f"Changelog agent failed: {e}")

        # Stage 6: Organize plans
        await self._update_progress("plans", "Organizing plans...")
        try:
            plans_result = await self.plans_agent.run()
            results.plans_structured = plans_result
            logger.info(f"Plans result: organized {plans_result.organized_count} plans")
        except Exception as e:
            logger.error(f"Plans agent failed: {e}")

        # Complete
        await self._update_progress("complete", "Documentation generation complete")

        logger.info(
            f"V2 documentation orchestration complete for product {self.product.id}: "
            f"imported={len(results.imported)}, generated={len(results.blueprints)}"
        )

        return results

    async def _run_v1(self) -> OrchestratorResult:
        """
        V1 flow: Legacy flow using BlueprintAgent for fixed Overview + Architecture.

        This is the original documentation flow, kept for backwards compatibility
        and as a fallback if v2 analysis/planning fails.
        """
        results = OrchestratorResult()

        logger.info(f"Starting v1 documentation orchestration for product {self.product.id}")

        # Update progress: scanning
        await self._update_progress("scanning", "Scanning repositories for documentation...")

        # Step 1: Check for existing docs/ folder
        repos = await self._get_linked_repos()
        logger.info(f"Found {len(repos)} linked repositories")

        for repo in repos:
            if not repo.full_name:
                continue

            try:
                docs_info = await self._scan_repo_docs(repo)

                if docs_info.has_docs_folder and docs_info.has_markdown_files:
                    logger.info(f"Found {len(docs_info.files)} doc files in {repo.full_name}")
                    # Import existing docs, structure into our folders
                    imported = await self._import_existing_docs(repo, docs_info)
                    results.imported.extend(imported)
            except Exception as e:
                logger.error(f"Failed to scan docs for {repo.full_name}: {e}")
                # Continue with other repos

        # Step 2: Delegate to sub-agents
        # Each agent checks what exists and fills gaps

        # Changelog
        await self._update_progress("changelog", "Processing changelog...")
        try:
            changelog_result = await self.changelog_agent.run()
            results.changelog = changelog_result
            logger.info(f"Changelog result: {changelog_result.action}")
        except Exception as e:
            logger.error(f"Changelog agent failed: {e}")

        # Blueprints (overview, architecture, etc.)
        await self._update_progress("blueprints", "Generating blueprints...")
        try:
            blueprint_result = await self.blueprint_agent.run()
            results.blueprints.extend(blueprint_result.documents)
            logger.info(f"Blueprint result: created {blueprint_result.created_count} new docs")
        except Exception as e:
            logger.error(f"Blueprint agent failed: {e}")

        # Plans structure (ensure folders exist, map any imported plans)
        await self._update_progress("plans", "Organizing plans...")
        try:
            plans_result = await self.plans_agent.run()
            results.plans_structured = plans_result
            logger.info(f"Plans result: organized {plans_result.organized_count} plans")
        except Exception as e:
            logger.error(f"Plans agent failed: {e}")

        # Update progress: complete
        await self._update_progress("complete", "Documentation generation complete")

        logger.info(
            f"V1 documentation orchestration complete for product {self.product.id}: "
            f"imported={len(results.imported)}, blueprints={len(results.blueprints)}"
        )

        return results

    async def _get_existing_docs(self) -> list[Document]:
        """Get all existing documents for this product."""
        if self.product.id is None:
            return []
        return await document_ops.get_by_product(
            self.db, self.product.user_id, self.product.id
        )

    async def _get_linked_repos(self) -> list[Repository]:
        """Get all GitHub-linked repositories for this product."""
        if self.product.id is None:
            return []
        return await repository_ops.get_github_repos_by_product(
            self.db, self.product.user_id, self.product.id
        )

    async def _scan_repo_docs(self, repo: Repository) -> DocsInfo:
        """Check if repo has docs/ folder and what's in it."""
        if not repo.full_name:
            return DocsInfo(has_docs_folder=False, has_markdown_files=False, files=[])

        owner, repo_name = repo.full_name.split("/", 1)
        tree = await self.github_service.get_repo_tree(
            owner, repo_name, repo.default_branch or "main"
        )

        docs_items: list[RepoTreeItem] = []
        for item in tree.all_items:
            # Include docs/ folder files and root-level changelog
            is_docs_file = item.path.startswith("docs/")
            is_changelog = item.path.lower() in ("changelog.md", "changes.md", "history.md")

            if (is_docs_file or is_changelog) and item.type == "blob":
                docs_items.append(item)

        return DocsInfo(
            has_docs_folder=any(item.path.startswith("docs/") for item in tree.all_items),
            has_markdown_files=any(item.path.endswith(".md") for item in docs_items),
            files=docs_items,
        )

    async def _import_existing_docs(
        self,
        repo: Repository,
        docs_info: DocsInfo,
    ) -> list[Document]:
        """Import existing docs and map to our folder structure."""
        if not repo.full_name:
            return []

        owner, repo_name = repo.full_name.split("/", 1)
        branch = repo.default_branch or "main"
        imported: list[Document] = []

        for item in docs_info.files:
            if not item.path.endswith(".md"):
                continue

            try:
                file_content = await self.github_service.get_file_content(
                    owner, repo_name, item.path, branch
                )
                if not file_content:
                    continue

                content = file_content.content

                # Map to our folder structure
                folder_path = map_path_to_folder(item.path)
                doc_type = infer_doc_type(item.path, content)

                doc = Document(
                    product_id=self.product.id,
                    user_id=self.product.user_id,
                    title=extract_title(content, item.path),
                    content=content,
                    type=doc_type,
                    folder={"path": folder_path} if folder_path else None,
                    repository_id=repo.id,
                )
                self.db.add(doc)
                imported.append(doc)

                logger.info(f"Imported doc: {item.path} -> {folder_path or 'root'}")

            except Exception as e:
                logger.error(f"Failed to import {item.path}: {e}")
                continue

        if imported:
            await self.db.commit()
            # Refresh all imported docs
            for doc in imported:
                await self.db.refresh(doc)

        return imported

    async def _update_progress(self, stage: str, message: str) -> None:
        """Update product's docs_generation_progress for frontend polling."""
        self.product.docs_generation_progress = {
            "stage": stage,
            "message": message,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.db.add(self.product)
        await self.db.commit()
        await self.db.refresh(self.product)
