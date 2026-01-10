"""
Content Generator service for generating prose content.

This service uses Claude Sonnet to generate documentation content for a project.
It receives pre-computed stats and pre-extracted architecture, focusing only
on writing quality prose content.

Part of the Analysis Agent refactoring (Phase 4).
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, cast

import anthropic
from anthropic import APIError, RateLimitError

from app.config import settings
from app.models.product import Product
from app.schemas.product_overview import OverviewArchitecture, OverviewStats
from app.services.github import RepoContext

logger = logging.getLogger(__name__)

# Model for content generation - Sonnet for quality prose
CONTENT_MODEL = "claude-sonnet-4-20250514"

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]


@dataclass
class ContentResult:
    """Result of content generation - prose fields only."""

    one_liner: str
    introduction: str
    status: str  # active, maintenance, archived, deprecated
    technical_content: str
    business_content: str
    features_content: str
    use_cases_content: str


class ContentGenerator:
    """
    Generate prose content using Claude Sonnet.

    This generator creates documentation content for a project:
    - One-liner tagline
    - Introduction paragraphs
    - Technical blueprint
    - Business overview
    - Key features
    - Use cases

    It receives pre-computed stats and architecture, focusing purely
    on writing clear, helpful documentation.
    """

    def __init__(self) -> None:
        """Initialize the content generator with Anthropic client."""
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate_content(
        self,
        product: Product,
        repo_contexts: list[RepoContext],
        stats: OverviewStats,
        architecture: OverviewArchitecture,
    ) -> ContentResult:
        """
        Generate prose content for a product.

        Args:
            product: The product being analyzed
            repo_contexts: Repository contexts with file contents
            stats: Pre-computed statistics from StatsExtractor
            architecture: Pre-extracted architecture from ArchitectureExtractor

        Returns:
            ContentResult with all prose content
        """
        if not repo_contexts:
            return self._create_empty_content(product)

        # Build focused prompt
        prompt = self._build_prompt(product, repo_contexts, stats, architecture)

        # Build tool schema
        tool_schema = self._build_tool_schema()

        logger.info(f"Generating content for {product.name} with {len(prompt)} chars of context")

        # Call Claude with retry logic
        return await self._call_with_retry(prompt, tool_schema, product)

    async def _call_with_retry(
        self,
        prompt: str,
        tool_schema: dict[str, Any],
        product: Product,
    ) -> ContentResult:
        """Call Claude API with exponential backoff retry."""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.messages.create(
                    model=CONTENT_MODEL,
                    max_tokens=12000,
                    tools=cast(Any, [tool_schema]),
                    tool_choice=cast(Any, {"type": "tool", "name": "save_content"}),
                    messages=[{"role": "user", "content": prompt}],
                )

                return self._parse_response(response, product)

            except (RateLimitError, APIError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Content generation error (attempt {attempt + 1}/{MAX_RETRIES}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Content generation failed after {MAX_RETRIES} attempts: {e}")

        # If we get here, all retries failed
        raise last_error or RuntimeError("Content generation failed after retries")

    def _build_prompt(
        self,
        product: Product,
        repo_contexts: list[RepoContext],
        stats: OverviewStats,
        architecture: OverviewArchitecture,
    ) -> str:
        """Build a focused prompt for prose content generation."""
        sections = [
            "You are writing documentation for a software project. Your goal is to create "
            "clear, helpful content that helps developers quickly understand what this "
            "project does and how it works.",
            "",
            "---",
            "",
            "## Project Information",
            "",
            f"**Name:** {product.name}",
            f"**Description:** {product.description or 'Not provided'}",
            "",
        ]

        # Add stats summary
        sections.extend(self._format_stats_summary(stats))

        # Add architecture summary
        sections.extend(self._format_architecture_summary(architecture))

        # Add key files for context
        sections.extend(self._format_key_files(repo_contexts))

        # Add instructions
        sections.extend(
            [
                "---",
                "",
                "## Your Task",
                "",
                "Generate documentation content using the `save_content` tool. Write for an "
                "audience of developers who are joining the project or evaluating it.",
                "",
                "### 1. One-Liner",
                "Write a single compelling sentence (max 150 characters) that captures what "
                "this project does. Think of it as the tagline you'd see on GitHub.",
                "",
                "### 2. Introduction",
                "Write 2-3 paragraphs providing an overview:",
                "- What problem does this solve?",
                "- What's the high-level approach?",
                "- What makes it interesting or unique?",
                "",
                "Use markdown formatting. Keep it engaging but informative.",
                "",
                "### 3. Status",
                "Determine the project status based on activity and state:",
                "- `active`: Regular commits, open issues being addressed",
                "- `maintenance`: Stable, occasional updates",
                "- `archived`: No longer actively developed",
                "- `deprecated`: Replaced or no longer recommended",
                "",
                "### 4. Technical Content (Technical Blueprint)",
                "Write detailed markdown covering:",
                "- System architecture and how components connect",
                "- Tech stack breakdown with version info if visible",
                "- Key patterns and design decisions",
                "- How data flows through the system",
                "",
                "### 5. Business Content (Business Overview)",
                "Write markdown explaining:",
                "- The business problem being solved",
                "- The value proposition",
                "- Target users or personas",
                "- How it fits in the market/ecosystem",
                "",
                "### 6. Features Content (Key Features)",
                "List and describe the main features:",
                "- Use bullet points or numbered lists",
                "- Group related features",
                "- Highlight what makes each feature valuable",
                "",
                "### 7. Use Cases Content",
                "Describe 3-4 concrete use cases:",
                "- Give each a name and brief scenario",
                "- Explain who benefits and how",
                "- Be specific with examples",
                "",
                "## Guidelines",
                "",
                "- Write in a professional but approachable tone",
                "- Use actual details from the codebase, don't invent features",
                "- Keep sections focused and scannable",
                "- Use markdown formatting (headers, lists, code blocks) appropriately",
                "- Aim for content that saves a new developer hours of exploration",
            ]
        )

        return "\n".join(sections)

    def _format_stats_summary(self, stats: OverviewStats) -> list[str]:
        """Format stats as a readable summary for the prompt."""
        sections = ["## Project Statistics", ""]

        # Timeline
        timeline_parts = []
        if stats.project_created:
            timeline_parts.append(f"Created: {stats.project_created}")
        if stats.last_activity:
            timeline_parts.append(f"Last activity: {stats.last_activity}")
        if stats.total_commits:
            timeline_parts.append(f"Commits: {stats.total_commits}")
        if timeline_parts:
            sections.append(f"**Timeline:** {' | '.join(timeline_parts)}")

        # Code metrics
        code_parts = []
        if stats.total_files:
            code_parts.append(f"{stats.total_files} files")
        if stats.total_lines_of_code:
            code_parts.append(f"~{stats.total_lines_of_code:,} lines")
        if stats.repo_count:
            code_parts.append(f"{stats.repo_count} repositories")
        if code_parts:
            sections.append(f"**Code:** {', '.join(code_parts)}")

        # Languages
        if stats.languages:
            lang_str = ", ".join(
                f"{lang.name} ({lang.percentage}%)" for lang in stats.languages[:5]
            )
            sections.append(f"**Languages:** {lang_str}")

        # GitHub stats
        github_parts = []
        if stats.stars:
            github_parts.append(f"{stats.stars} stars")
        if stats.forks:
            github_parts.append(f"{stats.forks} forks")
        if stats.contributor_count:
            github_parts.append(f"{stats.contributor_count} contributors")
        if github_parts:
            sections.append(f"**GitHub:** {', '.join(github_parts)}")

        # License
        if stats.license:
            sections.append(f"**License:** {stats.license}")

        sections.append("")
        return sections

    def _format_architecture_summary(self, architecture: OverviewArchitecture) -> list[str]:
        """Format architecture as a readable summary for the prompt."""
        sections = ["## Architecture Summary", ""]

        # API endpoints
        if architecture.api_endpoints:
            sections.append(f"**API Endpoints:** {len(architecture.api_endpoints)} endpoints")
            # Show a few examples
            for ep in architecture.api_endpoints[:5]:
                sections.append(f"  - {ep.method} {ep.path}: {ep.description}")
            if len(architecture.api_endpoints) > 5:
                sections.append(f"  - ... and {len(architecture.api_endpoints) - 5} more")
            sections.append("")

        # Database models
        if architecture.database_models:
            sections.append(f"**Database Models:** {len(architecture.database_models)} models")
            for model in architecture.database_models[:5]:
                fields_str = ", ".join(model.fields[:4])
                if len(model.fields) > 4:
                    fields_str += ", ..."
                sections.append(f"  - {model.name}: {fields_str}")
            if len(architecture.database_models) > 5:
                sections.append(f"  - ... and {len(architecture.database_models) - 5} more")
            sections.append("")

        # Services
        if architecture.services:
            sections.append(f"**Services:** {len(architecture.services)} services")
            for svc in architecture.services[:5]:
                sections.append(f"  - {svc.name}: {svc.description}")
            if len(architecture.services) > 5:
                sections.append(f"  - ... and {len(architecture.services) - 5} more")
            sections.append("")

        # Frontend pages
        if architecture.frontend_pages:
            sections.append(f"**Frontend Pages:** {len(architecture.frontend_pages)} pages")
            for page in architecture.frontend_pages[:5]:
                sections.append(f"  - {page.path} ({page.name}): {page.description}")
            if len(architecture.frontend_pages) > 5:
                sections.append(f"  - ... and {len(architecture.frontend_pages) - 5} more")
            sections.append("")

        return sections

    def _format_key_files(self, repo_contexts: list[RepoContext]) -> list[str]:
        """Format key files for context in the prompt."""
        sections = ["## Key Files", ""]

        for ctx in repo_contexts:
            if not ctx.files:
                continue

            if len(repo_contexts) > 1:
                sections.append(f"### Repository: {ctx.full_name}")
                sections.append("")

            for path, content in ctx.files.items():
                sections.append(f"**{path}:**")
                sections.append("```")
                # Truncate long files
                if len(content) > 6000:
                    sections.append(content[:6000])
                    sections.append(f"\n... (truncated, {len(content)} chars total)")
                else:
                    sections.append(content)
                sections.append("```")
                sections.append("")

        return sections

    def _build_tool_schema(self) -> dict[str, Any]:
        """Build the tool schema for content generation."""
        return {
            "name": "save_content",
            "description": "Save the generated documentation content",
            "input_schema": {
                "type": "object",
                "required": [
                    "one_liner",
                    "introduction",
                    "status",
                    "technical_content",
                    "business_content",
                    "features_content",
                    "use_cases_content",
                ],
                "properties": {
                    "one_liner": {
                        "type": "string",
                        "description": "Single compelling sentence (max 150 chars)",
                    },
                    "introduction": {
                        "type": "string",
                        "description": "2-3 paragraph overview with markdown formatting",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "maintenance", "archived", "deprecated"],
                        "description": "Project status based on activity",
                    },
                    "technical_content": {
                        "type": "string",
                        "description": "Technical blueprint markdown content",
                    },
                    "business_content": {
                        "type": "string",
                        "description": "Business overview markdown content",
                    },
                    "features_content": {
                        "type": "string",
                        "description": "Key features markdown content",
                    },
                    "use_cases_content": {
                        "type": "string",
                        "description": "Use cases markdown content",
                    },
                },
            },
        }

    def _parse_response(
        self,
        response: anthropic.types.Message,
        product: Product,
    ) -> ContentResult:
        """Parse Claude's response into ContentResult."""
        # Find the tool use block
        tool_use_block = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "save_content":
                tool_use_block = block
                break

        if not tool_use_block:
            logger.warning("Claude did not return a save_content tool use")
            return self._create_empty_content(product)

        data = cast(dict[str, Any], tool_use_block.input)

        return ContentResult(
            one_liner=data.get("one_liner", f"{product.name} - A software project"),
            introduction=data.get("introduction", "No introduction available."),
            status=data.get("status", "active"),
            technical_content=data.get("technical_content", "No technical content available."),
            business_content=data.get("business_content", "No business content available."),
            features_content=data.get("features_content", "No features content available."),
            use_cases_content=data.get("use_cases_content", "No use cases content available."),
        )

    def _create_empty_content(self, product: Product) -> ContentResult:
        """Create empty content when no repositories are available."""
        return ContentResult(
            one_liner=f"{product.name} - No repositories linked for analysis",
            introduction=(
                "This project has no GitHub repositories linked yet. "
                "Add repositories to enable AI-powered analysis and documentation generation."
            ),
            status="active",
            technical_content="No technical analysis available - no repositories linked.",
            business_content="No business analysis available - no repositories linked.",
            features_content="No features analysis available - no repositories linked.",
            use_cases_content="No use cases analysis available - no repositories linked.",
        )
