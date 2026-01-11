"""
File Selector package for dynamic architecture file identification.

This package uses Claude Haiku to intelligently identify architecturally
significant files from a repository's file tree.

Module structure:
- selector.py: Main FileSelector class
- types.py: Data types (FileSelectorInput, FileSelectorResult)
- constants.py: Configuration and pattern constants
- prompts.py: Prompt builders for AI selection
- fallback.py: Heuristic fallback logic
- parser.py: Response parsing utilities
"""

from app.services.file_selector.constants import (
    FALLBACK_PATTERNS,
    FILE_SELECTOR_MODEL,
    MAX_FILES_TO_SELECT,
    MAX_TREE_FILES,
    MIN_FILES_TO_SELECT,
    PRIORITY_DIRECTORIES,
)
from app.services.file_selector.fallback import heuristic_fallback, truncate_tree
from app.services.file_selector.parser import extract_references, parse_response
from app.services.file_selector.selector import FileSelector
from app.services.file_selector.types import FileSelectorInput, FileSelectorResult

__all__ = [
    # Main class
    "FileSelector",
    # Types
    "FileSelectorInput",
    "FileSelectorResult",
    # Constants
    "FILE_SELECTOR_MODEL",
    "MAX_FILES_TO_SELECT",
    "MAX_TREE_FILES",
    "MIN_FILES_TO_SELECT",
    "PRIORITY_DIRECTORIES",
    "FALLBACK_PATTERNS",
    # Utilities
    "heuristic_fallback",
    "truncate_tree",
    "parse_response",
    "extract_references",
]
