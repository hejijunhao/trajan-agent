"""
File selector response parsing.

Parses and validates Claude's JSON responses for file selection.
"""

import json
import re

from app.services.file_selector.constants import MAX_FILES_TO_SELECT


def parse_response(response_text: str, valid_files: set[str]) -> list[str]:
    """
    Parse the JSON response and validate file paths.

    Handles various response formats including:
    - Raw JSON arrays
    - JSON in markdown code blocks
    - JSON with extra whitespace

    Args:
        response_text: Raw response text from Claude
        valid_files: Set of valid file paths to filter against

    Returns:
        List of validated file paths (up to MAX_FILES_TO_SELECT)
    """
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


def extract_references(
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
                candidates = _resolve_import(match, file_dir, valid_paths)
                referenced.update(candidates)

    return list(referenced)


def _resolve_import(
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
