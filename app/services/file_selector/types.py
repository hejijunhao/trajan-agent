"""
File selector data types.

Data classes for file selection input and output.
"""

from dataclasses import dataclass

from app.services.framework_detector import DetectionResult


@dataclass
class FileSelectorInput:
    """Input for file selection."""

    repo_name: str
    description: str | None
    readme_content: str | None
    file_paths: list[str]
    framework_hints: DetectionResult | None = None


@dataclass
class FileSelectorResult:
    """Result of file selection."""

    selected_files: list[str]
    truncated: bool  # True if the input tree was truncated
    file_count_before_truncation: int
    used_fallback: bool = False  # True if heuristic fallback was used
