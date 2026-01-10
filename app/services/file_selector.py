"""
File Selector service for dynamic architecture file identification.

This service uses Claude Haiku to intelligently identify architecturally
significant files from a repository's file tree. It replaces hardcoded
regex patterns with LLM-based file selection.

Part of the Dynamic Architecture Extraction feature (Phases 1 + 4).
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass

import anthropic
from anthropic import APIError, RateLimitError

from app.config import settings
from app.services.framework_detector import (
    DetectionResult,
    format_framework_hints,
)

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

# Heuristic patterns for fallback file selection
FALLBACK_PATTERNS = [
    # Entry points
    r"^(main|index|app|server)\.(py|ts|js|go|rs|java)$",
    r"^src/(main|index|app)\.(py|ts|js|go|rs)$",
    # Routes / API
    r".*/routes?/.*\.(py|ts|js|go)$",
    r".*/api/.*\.(py|ts|js|go)$",
    r".*/(controllers?|handlers?)/.*\.(py|ts|js|go)$",
    # Models
    r".*/models?/.*\.(py|ts|js|go)$",
    r".*/schemas?/.*\.(py|ts|js)$",
    r".*/entities?/.*\.(py|ts|java)$",
    # Services
    r".*/services?/.*\.(py|ts|js|go)$",
    r".*/domain/.*\.(py|ts|js)$",
    # Frontend pages
    r".*/pages?/.*\.(tsx|jsx|vue|svelte)$",
    r".*/app/.*/page\.(tsx|jsx)$",
    r".*/views?/.*\.(tsx|jsx|vue)$",
    # Config
    r"^(pyproject\.toml|package\.json|Cargo\.toml|go\.mod)$",
]


@dataclass
class FileSelectorInput:
    """Input for file selection."""

    repo_name: str
    description: str | None
    readme_content: str | None
    file_paths: list[str]
    framework_hints: DetectionResult | None = None  # Phase 4: Framework detection results


@dataclass
class FileSelectorResult:
    """Result of file selection."""

    selected_files: list[str]
    truncated: bool  # True if the input tree was truncated
    file_count_before_truncation: int
    used_fallback: bool = False  # True if heuristic fallback was used


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
            file_paths = self._truncate_tree(file_paths)
            truncated = True
            logger.info(f"Truncated file tree from {original_count} to {len(file_paths)} files")

        # Build prompt (now includes framework hints if available)
        prompt = self._build_prompt(
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
            fallback_files = self._heuristic_fallback(file_paths, input_data.framework_hints)

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
        framework_hints: DetectionResult | None = None,
    ) -> str:
        """Build the prompt for file selection, including framework hints."""
        sections = [
            "You are analyzing a code repository to identify architecturally significant files.",
            "",
            "## Repository",
            f"Name: {repo_name}",
        ]

        if description:
            sections.append(f"Description: {description}")

        sections.append("")

        # Include framework hints if available (Phase 4)
        if framework_hints and framework_hints.frameworks:
            framework_section = format_framework_hints(framework_hints)
            if framework_section:
                sections.extend([framework_section, ""])

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
            ]
        )

        # Add framework-specific guidance if detected
        if framework_hints and framework_hints.suggested_directories:
            sections.extend(
                [
                    "",
                    "Based on the detected framework, pay special attention to these directories:",
                    ", ".join(f"`{d}`" for d in framework_hints.suggested_directories[:6]),
                ]
            )

        sections.extend(
            [
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

    def _heuristic_fallback(
        self,
        file_paths: list[str],
        framework_hints: DetectionResult | None = None,
    ) -> list[str]:
        """
        Select files using heuristic patterns when AI selection fails.

        Falls back to regex-based matching on common architecture patterns.
        Used as a safety net when Claude returns empty or insufficient results.

        Args:
            file_paths: List of all file paths in the repository
            framework_hints: Optional framework detection results for priority

        Returns:
            List of selected file paths (up to MAX_FILES_TO_SELECT)
        """
        selected: list[str] = []
        selected_set: set[str] = set()

        # Compile fallback patterns
        compiled_patterns = [re.compile(p) for p in FALLBACK_PATTERNS]

        # If framework hints exist, add framework-specific directories as priorities
        priority_dirs: list[str] = []
        if framework_hints and framework_hints.suggested_directories:
            priority_dirs = framework_hints.suggested_directories

        # First pass: files in framework priority directories
        for path in file_paths:
            if len(selected) >= MAX_FILES_TO_SELECT:
                break

            # Check if in priority directory
            in_priority = any(path.startswith(d) or f"/{d}" in path for d in priority_dirs)
            # Only include source files in priority directories, not tests or docs
            if (
                in_priority
                and path not in selected_set
                and self._is_source_file(path)
                and not self._is_test_file(path)
            ):
                selected.append(path)
                selected_set.add(path)

        # Second pass: files matching fallback patterns
        for path in file_paths:
            if len(selected) >= MAX_FILES_TO_SELECT:
                break

            if path in selected_set:
                continue

            for pattern in compiled_patterns:
                if pattern.search(path):
                    selected.append(path)
                    selected_set.add(path)
                    break

        # Third pass: grab entry points and common key files
        key_entry_points = [
            "main.py",
            "app.py",
            "server.py",
            "index.ts",
            "index.js",
            "main.ts",
            "main.go",
            "main.rs",
            "src/main.py",
            "src/index.ts",
            "src/app.ts",
            "app/main.py",
        ]

        for entry in key_entry_points:
            if len(selected) >= MAX_FILES_TO_SELECT:
                break
            if entry in file_paths and entry not in selected_set:
                selected.append(entry)
                selected_set.add(entry)

        logger.info(f"Heuristic fallback selected {len(selected)} files")
        return selected

    def _is_source_file(self, path: str) -> bool:
        """Check if a path is a source code file."""
        source_extensions = {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".scala",
            ".rb",
            ".php",
            ".cs",
            ".swift",
            ".vue",
            ".svelte",
        }
        return any(path.endswith(ext) for ext in source_extensions)

    def _is_test_file(self, path: str) -> bool:
        """Check if a path is likely a test file."""
        test_indicators = [
            "/test/",
            "/tests/",
            "/__tests__/",
            "/spec/",
            "/specs/",
            "_test.",
            ".test.",
            ".spec.",
            "test_",
        ]
        path_lower = path.lower()
        return any(ind in path_lower for ind in test_indicators)

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

        This is useful for repos where the initial selection missed important
        files that become apparent only after reading the code.

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
        referenced_files = self._extract_references(file_contents, set(file_paths))

        # Filter out already selected files
        already_set = set(already_selected)
        additional = [f for f in referenced_files if f not in already_set]

        if not additional:
            logger.info(f"Second pass: no additional files found for {repo_name}")
            return []

        # Build a refined prompt for second pass
        prompt = self._build_refinement_prompt(
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

    def _extract_references(
        self,
        file_contents: dict[str, str],
        valid_paths: set[str],
    ) -> list[str]:
        """
        Extract file references (imports, requires) from file contents.

        Args:
            file_contents: Dict mapping file paths to their contents
            valid_paths: Set of valid file paths in the repository

        Returns:
            List of referenced file paths that exist in the repository
        """
        referenced: set[str] = set()

        # Patterns for common import statements
        import_patterns = [
            # Python: from x import y, import x
            r'from\s+["\']?([.\w/]+)["\']?\s+import',
            r'import\s+["\']?([.\w/]+)["\']?',
            # JS/TS: import x from 'y', require('y')
            r'import\s+.*\s+from\s+["\']([^"\']+)["\']',
            r'require\s*\(\s*["\']([^"\']+)["\']\s*\)',
            # Go: import "x"
            r'import\s+["\']([^"\']+)["\']',
            # Rust: use x, mod x
            r"use\s+([:\w]+)",
            r"mod\s+(\w+)",
        ]

        for file_path, content in file_contents.items():
            file_dir = "/".join(file_path.split("/")[:-1]) if "/" in file_path else ""

            for pattern in import_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    # Try to resolve the import to a file path
                    candidates = self._resolve_import(match, file_dir, valid_paths)
                    referenced.update(candidates)

        return list(referenced)

    def _resolve_import(
        self,
        import_path: str,
        current_dir: str,
        valid_paths: set[str],
    ) -> list[str]:
        """
        Try to resolve an import statement to actual file paths.

        Args:
            import_path: The import path from the source code
            current_dir: Directory of the file containing the import
            valid_paths: Set of valid file paths in the repository

        Returns:
            List of matching file paths
        """
        resolved: list[str] = []

        # Clean up the import path
        import_path = import_path.replace(".", "/").strip("/")

        # Common extensions to try
        extensions = ["", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"]

        # Try relative paths
        if current_dir:
            for ext in extensions:
                candidate = f"{current_dir}/{import_path}{ext}"
                if candidate in valid_paths:
                    resolved.append(candidate)

                # Also try index files
                candidate = f"{current_dir}/{import_path}/index{ext}"
                if candidate in valid_paths:
                    resolved.append(candidate)

        # Try absolute paths from repo root
        for ext in extensions:
            candidate = f"{import_path}{ext}"
            if candidate in valid_paths:
                resolved.append(candidate)

            # Try common source directories
            for prefix in ["src/", "app/", "lib/", "pkg/", "internal/"]:
                candidate = f"{prefix}{import_path}{ext}"
                if candidate in valid_paths:
                    resolved.append(candidate)

        return resolved

    def _build_refinement_prompt(
        self,
        repo_name: str,
        file_contents: dict[str, str],
        candidate_files: list[str],
        max_to_select: int,
    ) -> str:
        """Build prompt for second-pass refinement selection."""
        # Summarize the files we've already read
        file_summaries = []
        for path, content in list(file_contents.items())[:10]:  # Limit to avoid token explosion
            # Just show first 50 lines of each file
            lines = content.split("\n")[:50]
            truncated = "\n".join(lines)
            if len(content.split("\n")) > 50:
                truncated += "\n... (truncated)"
            file_summaries.append(f"### {path}\n```\n{truncated}\n```")

        files_section = "\n\n".join(file_summaries)

        return f"""You are analyzing code from repository {repo_name}.

Based on the files we've already read, identify additional files that would help complete our understanding of the architecture.

## Files Already Read

{files_section}

## Candidate Files to Consider

{chr(10).join(candidate_files)}

## Task

From the candidate files above, select up to {max_to_select} files that are:
1. Referenced or imported by the files we've read
2. Define types, interfaces, or models used by the files we've read
3. Contain related business logic or utilities

Return ONLY a JSON array of file paths. Example:

```json
["src/types/user.ts", "src/utils/validation.py"]
```"""
