"""
File selector fallback logic.

Provides heuristic-based file selection when AI selection fails or returns
insufficient results.
"""

import logging
import re

from app.services.file_selector.constants import (
    FALLBACK_PATTERNS,
    KEY_ENTRY_POINTS,
    MAX_FILES_TO_SELECT,
    MAX_TREE_FILES,
    PRIORITY_DIRECTORIES,
    SOURCE_EXTENSIONS,
    TEST_INDICATORS,
)
from app.services.framework_detector import DetectionResult

logger = logging.getLogger(__name__)


def truncate_tree(file_paths: list[str]) -> list[str]:
    """
    Truncate a large file tree to MAX_TREE_FILES.

    Prioritization strategy:
    1. Files in priority directories (src/, app/, api/, etc.)
    2. Files at shallower depths
    3. Source code files over config/docs

    Args:
        file_paths: List of all file paths

    Returns:
        Truncated list of file paths
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


def is_source_file(path: str) -> bool:
    """Check if a path is a source code file."""
    return any(path.endswith(ext) for ext in SOURCE_EXTENSIONS)


def is_test_file(path: str) -> bool:
    """Check if a path is likely a test file."""
    path_lower = path.lower()
    return any(ind in path_lower for ind in TEST_INDICATORS)


def heuristic_fallback(
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
            and is_source_file(path)
            and not is_test_file(path)
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
    for entry in KEY_ENTRY_POINTS:
        if len(selected) >= MAX_FILES_TO_SELECT:
            break
        if entry in file_paths and entry not in selected_set:
            selected.append(entry)
            selected_set.add(entry)

    logger.info(f"Heuristic fallback selected {len(selected)} files")
    return selected
