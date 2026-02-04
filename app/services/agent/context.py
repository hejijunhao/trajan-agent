"""Context builder for the CLI Agent.

Assembles project context from existing domain operations
into a formatted string for the agent's system prompt.
"""

import uuid as uuid_pkg
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import (
    document_ops,
    product_ops,
    progress_summary_ops,
    repository_ops,
    work_item_ops,
)


class ContextBuilder:
    """Builds context string for the agent from project data."""

    async def build(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
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

        return "\n\n".join(sections) if sections else "No project data available."

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
