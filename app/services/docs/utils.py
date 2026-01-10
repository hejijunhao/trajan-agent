"""
Shared utilities for documentation services.

Contains common functions used by orchestrator, sync_service, and agents.
"""

import re


def extract_title(content: str, path: str) -> str:
    """
    Extract title from markdown content or filename.

    Tries to get the first H1 heading from the content. If not found,
    falls back to formatting the filename as a title.

    Args:
        content: Markdown content
        path: File path (used for fallback)

    Returns:
        Extracted title string
    """
    # Try to get first H1
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()

    # Fallback to filename
    filename = path.split("/")[-1]
    title = filename.replace(".md", "").replace("-", " ").replace("_", " ")
    return title.title()


def map_path_to_folder(path: str) -> str | None:
    """
    Map GitHub/source path to Trajan folder structure.

    Analyzes the path to determine which folder the document should
    be organized into (blueprints, plans, executing, completions, archive).

    Classification priority:
    1. Folder structure patterns (e.g., /plans/, /blueprints/)
    2. Filename patterns (e.g., "implementation-plan.md")
    3. Default to blueprints for docs/ folder

    Args:
        path: Source file path

    Returns:
        Folder path string, or None for root-level docs (e.g., changelog)
    """
    path_lower = path.lower()

    # Changelog stays at root
    if any(p in path_lower for p in ["changelog", "changes", "history"]):
        return None

    # 1. Map known folder patterns first (explicit structure takes precedence)
    if any(p in path_lower for p in ["/blueprints/", "/overview/", "/architecture/"]):
        return "blueprints"
    if any(p in path_lower for p in ["/plans/", "/roadmap/", "/planning/"]):
        return "plans"
    if any(p in path_lower for p in ["/executing/", "/in-progress/", "/wip/"]):
        return "executing"
    if any(p in path_lower for p in ["/completions/", "/completed/", "/done/", "/finished/"]):
        # Try to extract date from path
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", path)
        if date_match:
            return f"completions/{date_match.group(1)}"
        return "completions"
    if any(p in path_lower for p in ["/archive/", "/old/", "/deprecated/"]):
        return "archive"

    # 2. Check filename patterns before defaulting
    # Extract filename from path
    filename_lower = path_lower.split("/")[-1]

    # Plan indicators in filename (more specific patterns first)
    plan_patterns = [
        "-plan",
        "_plan",
        "-plan.",
        "_plan.",  # Suffix patterns
        "plan-",
        "plan_",  # Prefix patterns
        "-roadmap",
        "_roadmap",
        "roadmap-",
        "roadmap_",
        "-proposal",
        "_proposal",
        "proposal-",
        "proposal_",
        "-implementation",
        "_implementation",
        "phase-",
        "phase_",  # Phase documents are typically plans
    ]
    if any(p in filename_lower for p in plan_patterns):
        return "plans"

    # Completion indicators in filename
    completion_patterns = [
        "-completion",
        "_completion",
        "completion-",
        "completion_",
        "-report",
        "_report",  # Reports are typically completions
        "-completed",
        "_completed",
    ]
    if any(p in filename_lower for p in completion_patterns):
        return "completions"

    # 3. Default for docs/ folder
    if path.startswith("docs/"):
        return "blueprints"

    return None


def infer_doc_type(path: str, _content: str | None = None) -> str:
    """
    Infer document type from path and optionally content.

    Args:
        path: File path
        content: Optional markdown content (currently unused, reserved for future)

    Returns:
        Document type string (changelog, architecture, plan, blueprint, note)
    """
    path_lower = path.lower()

    if any(p in path_lower for p in ["changelog", "changes", "history"]):
        return "changelog"
    if "architecture" in path_lower:
        return "architecture"
    if any(p in path_lower for p in ["plan", "roadmap", "proposal"]):
        return "plan"
    if "readme" in path_lower:
        return "blueprint"
    if "api" in path_lower:
        return "architecture"
    if any(p in path_lower for p in ["guide", "tutorial"]):
        return "note"

    return "blueprint"


def generate_github_path(title: str, folder_path: str | None, doc_type: str) -> str:
    """
    Generate a GitHub file path for a document.

    Args:
        title: Document title
        folder_path: Folder path (e.g., "blueprints", "plans")
        doc_type: Document type

    Returns:
        Generated file path for GitHub
    """
    # Slugify title
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")

    if not slug:
        slug = "untitled"

    if doc_type == "changelog":
        return "docs/changelog.md"

    if not folder_path:
        return f"docs/{slug}.md"

    return f"docs/{folder_path}/{slug}.md"
