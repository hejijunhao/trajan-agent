"""
File Selector service for dynamic architecture file identification.

This service uses Claude Haiku to intelligently identify architecturally
significant files from a repository's file tree.
"""

import asyncio
import json
import logging

import anthropic
from anthropic import APIError, RateLimitError

from app.config import settings
from app.services.file_selector.constants import (
    FILE_SELECTOR_MODEL,
    MAX_FILES_TO_SELECT,
    MAX_RETRIES,
    MAX_TOKENS,
    MAX_TREE_FILES,
    MIN_FILES_TO_SELECT,
    RETRY_DELAYS,
)
from app.services.file_selector.fallback import heuristic_fallback, truncate_tree
from app.services.file_selector.parser import extract_references, parse_response
from app.services.file_selector.prompts import build_refinement_prompt, build_selection_prompt
from app.services.file_selector.types import FileSelectorInput, FileSelectorResult

logger = logging.getLogger(__name__)


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

        Uses AI-based selection with automatic fallback to heuristics if:
        - Claude returns empty results
        - API errors exhaust all retries
        - Framework hints are used to improve selection quality

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
            file_paths = truncate_tree(file_paths)
            truncated = True
            logger.info(f"Truncated file tree from {original_count} to {len(file_paths)} files")

        # Build prompt (now includes framework hints if available)
        prompt = build_selection_prompt(
            repo_name=input_data.repo_name,
            description=input_data.description,
            readme_content=input_data.readme_content,
            file_paths=file_paths,
            framework_hints=input_data.framework_hints,
        )

        # Call Claude with retry logic
        selected_files: list[str] = []
        used_fallback = False

        try:
            selected_files = await self._call_with_retry(prompt, file_paths)
        except (APIError, RateLimitError) as e:
            logger.warning(f"FileSelector API failed, using fallback: {e}")
            used_fallback = True

        # If Claude returned empty/insufficient, use heuristic fallback
        if len(selected_files) < MIN_FILES_TO_SELECT // 2:
            logger.info(
                f"FileSelector returned {len(selected_files)} files, "
                "supplementing with heuristic fallback"
            )
            fallback_files = heuristic_fallback(file_paths, input_data.framework_hints)

            # Merge: keep AI selections, add heuristic ones that aren't duplicates
            existing = set(selected_files)
            for f in fallback_files:
                if f not in existing and len(selected_files) < MAX_FILES_TO_SELECT:
                    selected_files.append(f)
                    existing.add(f)

            used_fallback = True

        return FileSelectorResult(
            selected_files=selected_files,
            truncated=truncated,
            file_count_before_truncation=original_count,
            used_fallback=used_fallback,
        )

    async def refine_selection(
        self,
        repo_name: str,
        file_paths: list[str],
        already_selected: list[str],
        file_contents: dict[str, str],
        max_additional: int = 20,
    ) -> list[str]:
        """
        Second-pass file selection based on file content analysis.

        After the first pass identifies initial files and they've been read,
        this method can identify additional related files based on:
        - Import statements and dependencies discovered in first-pass files
        - Type definitions referenced but not yet fetched
        - Related modules identified from the code structure

        Args:
            repo_name: Repository name for logging
            file_paths: Complete list of file paths in the repo
            already_selected: Files already selected in first pass
            file_contents: Dict of file path -> content for first-pass files
            max_additional: Maximum additional files to select (default: 20)

        Returns:
            List of additional file paths to fetch (not including already_selected)
        """
        if not file_contents:
            return []

        # Extract imports and references from the file contents
        referenced_files = extract_references(file_contents, set(file_paths))

        # Filter out already selected files
        already_set = set(already_selected)
        additional = [f for f in referenced_files if f not in already_set]

        if not additional:
            logger.info(f"Second pass: no additional files found for {repo_name}")
            return []

        # Build a refined prompt for second pass
        prompt = build_refinement_prompt(
            repo_name=repo_name,
            file_contents=file_contents,
            candidate_files=additional[:100],  # Limit candidates sent to prompt
            max_to_select=max_additional,
        )

        try:
            selected = await self._call_with_retry(prompt, additional)
            logger.info(f"Second pass: selected {len(selected)} additional files for {repo_name}")
            return selected[:max_additional]
        except (APIError, RateLimitError) as e:
            logger.warning(f"Second pass failed for {repo_name}: {e}")
            # Return top candidates from heuristic extraction
            return additional[:max_additional]

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
                selected = parse_response(response_text, valid_set)

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
