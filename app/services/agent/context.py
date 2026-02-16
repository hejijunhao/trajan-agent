"""Context builder for the CLI Agent.

Assembles project context from existing domain operations
into a formatted string for the agent's system prompt.
"""

import hashlib
import logging
import uuid as uuid_pkg
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import (
    document_ops,
    product_ops,
    progress_summary_ops,
    repository_ops,
    work_item_ops,
)
from app.services.github import GitHubService
from app.services.github.cache import agent_context_cache

logger = logging.getLogger(__name__)

# Max chars for the entire GitHub context section
_GITHUB_CONTEXT_CHAR_LIMIT = 2000
_GITHUB_MAX_REPOS = 3


class ContextBuilder:
    """Builds context string for the agent from project data."""

    async def build(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        github_token: str | None = None,
    ) -> str:
        """Fetch and format all relevant project context into a string."""
        sections: list[str] = []

        # Product info
        product = await product_ops.get(db, product_id)
        if product:
            sections.append(self._format_product(product))

        # Repositories
        repos = await repository_ops.get_by_product(db, product_id, limit=50)
        if repos:
            sections.append(self._format_repositories(repos))

        # Work items
        items = await work_item_ops.get_by_product(db, product_id, limit=50)
        if items:
            sections.append(self._format_work_items(items))

        # Documents
        docs = await document_ops.get_by_product(db, product_id, limit=50)
        if docs:
            sections.append(self._format_documents(docs))

        # Progress summary (last 7 days)
        summary = await progress_summary_ops.get_by_product_period(db, product_id, "7d")
        if summary:
            sections.append(self._format_progress(summary))

        # Live GitHub activity
        if github_token and repos:
            gh_context = await self._fetch_github_context(github_token, repos)
            if gh_context:
                sections.append(gh_context)

        return "\n\n".join(sections) if sections else "No project data available."

    async def _fetch_github_context(
        self,
        github_token: str,
        repos: Sequence[object],
    ) -> str | None:
        """Fetch live GitHub activity for the product's repos.

        Returns a formatted context section, or None if all calls fail.
        Gracefully handles token revocation, rate limits, and access errors.
        Results are cached for 60s to avoid hammering GitHub during rapid chat.
        """
        # Build cache key from repo names (token not included — same repos = same data)
        repo_names = sorted(
            getattr(r, "full_name", "") for r in repos[:_GITHUB_MAX_REPOS]
        )
        cache_key = hashlib.md5(
            f"agent_ctx:{':'.join(repo_names)}".encode()
        ).hexdigest()

        cached: str | None = agent_context_cache.get(cache_key)
        if cached is not None:
            return cached

        gh = GitHubService(github_token)
        repo_sections: list[str] = []

        for repo in repos[:_GITHUB_MAX_REPOS]:
            full_name = getattr(repo, "full_name", None)
            if not full_name or "/" not in full_name:
                continue
            owner, name = full_name.split("/", 1)

            try:
                section = await self._fetch_single_repo_context(gh, owner, name)
                if section:
                    repo_sections.append(section)
            except Exception:
                logger.warning("GitHub context fetch failed for %s", full_name, exc_info=True)
                continue

        if not repo_sections:
            return None

        result = "## GitHub Activity (Live)\n" + "\n".join(repo_sections)
        result = result[:_GITHUB_CONTEXT_CHAR_LIMIT]
        agent_context_cache[cache_key] = result
        return result

    @staticmethod
    async def _fetch_single_repo_context(
        gh: GitHubService,
        owner: str,
        name: str,
    ) -> str | None:
        """Fetch commits, PRs, and issues for a single repo."""
        lines: list[str] = [f"### {owner}/{name}"]
        has_data = False

        # Recent commits
        commits: list[dict[str, Any]] = await gh.get_recent_commits(owner, name, per_page=5)
        if commits:
            has_data = True
            lines.append("Recent commits:")
            for c in commits:
                msg = c["message"][:72]
                lines.append(f"  - {c['sha']} {msg} ({c['author']})")

        # Open PRs
        pulls: list[dict[str, Any]] = await gh.get_open_pulls(owner, name, per_page=5)
        if pulls:
            has_data = True
            lines.append("Open PRs:")
            for pr in pulls:
                title = pr["title"][:60]
                lines.append(f"  - #{pr['number']} {title} (by {pr['author']})")

        # Open issues
        issues: list[dict[str, Any]] = await gh.get_open_issues(owner, name, per_page=5)
        if issues:
            has_data = True
            lines.append("Open issues:")
            for issue in issues:
                title = issue["title"][:60]
                labels = ", ".join(issue["labels"][:3])
                line = f"  - #{issue['number']} {title}"
                if labels:
                    line += f" [{labels}]"
                lines.append(line)

        return "\n".join(lines) if has_data else None

    @staticmethod
    def _format_product(product: object) -> str:
        """Format product info section."""
        lines = ["## Product"]
        lines.append(f"Name: {getattr(product, 'name', 'Unknown')}")
        desc = getattr(product, "description", None)
        if desc:
            lines.append(f"Description: {desc}")
        overview = getattr(product, "product_overview", None)
        if overview:
            text = str(overview) if not isinstance(overview, str) else overview
            lines.append(f"Overview: {text[:500]}")
        return "\n".join(lines)

    @staticmethod
    def _format_repositories(repos: Sequence[object]) -> str:
        """Format repositories section."""
        lines = [f"## Repositories ({len(repos)})"]
        for repo in repos:
            name = getattr(repo, "full_name", None) or getattr(repo, "name", "Unknown")
            lang = getattr(repo, "language", None) or "Unknown"
            desc = getattr(repo, "description", None) or ""
            stars = getattr(repo, "stars_count", 0) or 0
            line = f"- {name} [{lang}]"
            if stars:
                line += f" ★{stars}"
            if desc:
                line += f" — {desc[:80]}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _format_work_items(items: Sequence[object]) -> str:
        """Format work items section."""
        lines = [f"## Work Items ({len(items)})"]
        for item in items:
            title = getattr(item, "title", "Untitled")
            item_type = getattr(item, "type", "task")
            status = getattr(item, "status", "unknown")
            priority = getattr(item, "priority", None)
            line = f"- [{status}] {title} ({item_type})"
            if priority:
                line += f" priority={priority}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _format_documents(docs: Sequence[object]) -> str:
        """Format documents section."""
        lines = [f"## Documents ({len(docs)})"]
        for doc in docs:
            title = getattr(doc, "title", "Untitled")
            doc_type = getattr(doc, "type", "document")
            pinned = getattr(doc, "is_pinned", False)
            line = f"- {title} ({doc_type})"
            if pinned:
                line += " [pinned]"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _format_progress(summary: object) -> str:
        """Format progress summary section."""
        lines = ["## Recent Activity (Last 7 Days)"]
        text = getattr(summary, "summary_text", None)
        if text:
            lines.append(text[:500])
        commits = getattr(summary, "total_commits", 0)
        contributors = getattr(summary, "total_contributors", 0)
        if commits or contributors:
            lines.append(f"Stats: {commits} commits, {contributors} contributors")
        return "\n".join(lines)
