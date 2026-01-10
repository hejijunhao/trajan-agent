"""
DocumentOrchestrator - Coordinates the entire documentation generation process.

This is the top-level orchestrator that:
1. Scans repositories for existing documentation
2. Imports existing docs into our folder structure
3. Delegates to sub-agents for specific documentation tasks
4. Coordinates progress updates for frontend polling
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.repository_operations import repository_ops
from app.models.document import Document
from app.models.product import Product
from app.models.repository import Repository
from app.services.docs.blueprint_agent import BlueprintAgent
from app.services.docs.changelog_agent import ChangelogAgent
from app.services.docs.plans_agent import PlansAgent
from app.services.docs.types import DocsInfo, OrchestratorResult
from app.services.docs.utils import extract_title, infer_doc_type, map_path_to_folder
from app.services.github import GitHubService
from app.services.github.types import RepoTreeItem

logger = logging.getLogger(__name__)


class DocumentOrchestrator:
    """
    Tier 1 orchestrator that coordinates documentation generation.

    Responsibilities:
    1. Check if repos have existing docs/ folders
    2. Scan and import existing documentation
    3. Delegate to sub-agents for their domains
    4. Ensure all docs are structured into our opinionated folders
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

        # Sub-agents
        self.changelog_agent = ChangelogAgent(db, product, github_service)
        self.blueprint_agent = BlueprintAgent(db, product, github_service)
        self.plans_agent = PlansAgent(db, product, github_service)

    async def run(self) -> OrchestratorResult:
        """
        Main entry point for documentation generation.

        Follows import-first workflow:
        1. Scan repos for existing docs
        2. Import and structure existing docs
        3. Run sub-agents to fill gaps

        Returns:
            OrchestratorResult with all processing results
        """
        results = OrchestratorResult()

        logger.info(f"Starting documentation orchestration for product {self.product.id}")

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
            f"Documentation orchestration complete for product {self.product.id}: "
            f"imported={len(results.imported)}, blueprints={len(results.blueprints)}"
        )

        return results

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
