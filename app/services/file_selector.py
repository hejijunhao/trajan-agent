"""
File Selector service for dynamic architecture file identification.

This service uses Claude Haiku to intelligently identify architecturally
significant files from a repository's file tree. It replaces hardcoded
regex patterns with LLM-based file selection.

Part of the Dynamic Architecture Extraction feature (Phase 1).
"""

import asyncio
import json
import logging
from dataclasses import dataclass

import anthropic
from anthropic import APIError, RateLimitError

from app.config import settings

logger = logging.getLogger(__name__)

# Model for file selection - Haiku for speed and cost efficiency
FILE_SELECTOR_MODEL = "claude-3-5-haiku-20241022"

# Limits
MAX_FILES_TO_SELECT = 50
MIN_FILES_TO_SELECT = 10
MAX_TREE_FILES = 1000  # Truncate tree if larger than this
MAX_TOKENS = 2000

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]

# Priority directories for tree truncation
# When truncating large trees, prioritize these directories
PRIORITY_DIRECTORIES = [
    "src/",
    "app/",
    "lib/",
    "api/",
    "routes/",
    "pages/",
    "components/",
    "models/",
    "services/",
    "controllers/",
    "handlers/",
    "domain/",
    "core/",
    "pkg/",
    "cmd/",
    "internal/",
]


@dataclass
class FileSelectorInput:
    """Input for file selection."""

    repo_name: str
    description: str | None
    readme_content: str | None
    file_paths: list[str]


@dataclass
class FileSelectorResult:
    """Result of file selection."""

    selected_files: list[str]
    truncated: bool  # True if the input tree was truncated
    file_count_before_truncation: int


class FileSelector:
    """
    Select architecturally significant files from a repository tree.

    Uses Claude Haiku to intelligently identify files that provide the most
    insight into a codebase's architecture:
    - API endpoints and route definitions
    - Database models and schemas
    - Services and business logic
    - Frontend pages and components
    - Entry points and configuration
    """

    def __init__(self) -> None:
        """Initialize the file selector with Anthropic client."""
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def select_files(self, input_data: FileSelectorInput) -> FileSelectorResult:
        """
        Select architecturally significant files from a repository tree.

        Args:
            input_data: Repository information including file tree

        Returns:
            FileSelectorResult with selected file paths
        """
        original_count = len(input_data.file_paths)

        # Handle empty or very small repos
        if not input_data.file_paths:
            return FileSelectorResult(
                selected_files=[],
                truncated=False,
                file_count_before_truncation=0,
            )

        # If fewer files than our minimum, just return all of them
        if len(input_data.file_paths) <= MIN_FILES_TO_SELECT:
            return FileSelectorResult(
                selected_files=input_data.file_paths,
                truncated=False,
                file_count_before_truncation=original_count,
            )

        # Truncate tree if too large
        file_paths = input_data.file_paths
        truncated = False

        if len(file_paths) > MAX_TREE_FILES:
            file_paths = self._truncate_tree(file_paths)
            truncated = True
            logger.info(f"Truncated file tree from {original_count} to {len(file_paths)} files")

        # Build prompt
        prompt = self._build_prompt(
            repo_name=input_data.repo_name,
            description=input_data.description,
            readme_content=input_data.readme_content,
            file_paths=file_paths,
        )

        # Call Claude with retry logic
        selected_files = await self._call_with_retry(prompt, file_paths)

        return FileSelectorResult(
            selected_files=selected_files,
            truncated=truncated,
            file_count_before_truncation=original_count,
        )

    def _truncate_tree(self, file_paths: list[str]) -> list[str]:
        """
        Truncate a large file tree to MAX_TREE_FILES.

        Prioritization strategy:
        1. Files in priority directories (src/, app/, api/, etc.)
        2. Files at shallower depths
        3. Source code files over config/docs
        """
        # Categorize files
        priority_files: list[str] = []
        other_files: list[str] = []

        for path in file_paths:
            is_priority = any(path.startswith(d) or f"/{d}" in path for d in PRIORITY_DIRECTORIES)
            if is_priority:
                priority_files.append(path)
            else:
                other_files.append(path)

        # Sort by depth (shallower first) within each category
        priority_files.sort(key=lambda p: p.count("/"))
        other_files.sort(key=lambda p: p.count("/"))

        # Take priority files first, then fill with others
        result = priority_files[:MAX_TREE_FILES]
        remaining_slots = MAX_TREE_FILES - len(result)

        if remaining_slots > 0:
            result.extend(other_files[:remaining_slots])

        return result

    def _build_prompt(
        self,
        repo_name: str,
        description: str | None,
        readme_content: str | None,
        file_paths: list[str],
    ) -> str:
        """Build the prompt for file selection."""
        sections = [
            "You are analyzing a code repository to identify architecturally significant files.",
            "",
            "## Repository",
            f"Name: {repo_name}",
        ]

        if description:
            sections.append(f"Description: {description}")

        sections.append("")

        # Include README if available (truncated to avoid token limits)
        if readme_content:
            readme_truncated = readme_content[:3000]
            if len(readme_content) > 3000:
                readme_truncated += "\n... (truncated)"
            sections.extend(
                [
                    "## README",
                    readme_truncated,
                    "",
                ]
            )

        # File tree as simple list
        file_tree_str = "\n".join(file_paths)
        sections.extend(
            [
                "## File Tree",
                f"Total files: {len(file_paths)}",
                "",
                file_tree_str,
                "",
                "## Task",
                "",
                f"Select {MIN_FILES_TO_SELECT}-{MAX_FILES_TO_SELECT} files that would best help "
                "understand this codebase's architecture. Focus on:",
                "",
                "1. **API/Routes** - Files defining HTTP endpoints, REST routes, GraphQL resolvers",
                "2. **Data Models** - Database schemas, entities, type definitions",
                "3. **Services** - Business logic, domain services, use cases",
                "4. **Frontend Pages** - Page components, views, route definitions",
                "5. **Entry Points** - Main application files, configuration",
                "",
                "Prioritize:",
                "- Entry points and core logic over utilities/helpers",
                "- Type definitions and interfaces",
                "- Files that define structure rather than implement details",
                "",
                "Return ONLY a JSON array of file paths. Include only files that exist in the "
                "tree above. Example:",
                "",
                "```json",
                '["src/routes/api.ts", "src/models/user.py", "app/main.py"]',
                "```",
            ]
        )

        return "\n".join(sections)

    async def _call_with_retry(
        self,
        prompt: str,
        valid_files: list[str],
    ) -> list[str]:
        """Call Claude API with exponential backoff retry."""
        last_error: Exception | None = None
        valid_set = set(valid_files)

        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.messages.create(
                    model=FILE_SELECTOR_MODEL,
                    max_tokens=MAX_TOKENS,
                    messages=[{"role": "user", "content": prompt}],
                )

                # Extract text from response
                first_block = response.content[0]
                response_text = (
                    first_block.text if hasattr(first_block, "text") else str(first_block)
                )

                # Parse JSON response
                selected = self._parse_response(response_text, valid_set)

                if selected:
                    logger.info(f"FileSelector selected {len(selected)} files")
                    return selected

                # If parsing failed or empty, log and continue to retry
                logger.warning(
                    f"FileSelector returned empty/invalid response, attempt {attempt + 1}"
                )

            except (RateLimitError, APIError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        f"FileSelector API error (attempt {attempt + 1}/{MAX_RETRIES}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"FileSelector failed after {MAX_RETRIES} attempts: {e}")

            except json.JSONDecodeError as e:
                logger.warning(f"FileSelector JSON parse error: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAYS[attempt])

        # If all retries failed, return empty list (caller should handle fallback)
        logger.error("FileSelector exhausted all retries, returning empty list")
        if last_error:
            raise last_error
        return []

    def _parse_response(self, response_text: str, valid_files: set[str]) -> list[str]:
        """Parse the JSON response and validate file paths."""
        # Try to extract JSON from response
        # Handle cases where response might have markdown code blocks
        text = response_text.strip()

        # Remove markdown code block if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```)
            lines = lines[1:]
            # Remove last line (```)
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON array in the response
            import re

            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(parsed, list):
            return []

        # Filter to only valid files and limit
        selected = [f for f in parsed if isinstance(f, str) and f in valid_files]

        return selected[:MAX_FILES_TO_SELECT]
