"""
File selector prompt builders.

Functions for building prompts sent to Claude for file selection.
"""

from app.services.file_selector.constants import MAX_FILES_TO_SELECT, MIN_FILES_TO_SELECT
from app.services.framework_detector import DetectionResult, format_framework_hints


def build_selection_prompt(
    repo_name: str,
    description: str | None,
    readme_content: str | None,
    file_paths: list[str],
    framework_hints: DetectionResult | None = None,
) -> str:
    """
    Build the prompt for initial file selection.

    Args:
        repo_name: Repository name
        description: Optional repository description
        readme_content: Optional README content
        file_paths: List of all file paths in the repo
        framework_hints: Optional framework detection results

    Returns:
        Formatted prompt string for Claude
    """
    sections = [
        "You are analyzing a code repository to identify architecturally significant files.",
        "",
        "## Repository",
        f"Name: {repo_name}",
    ]

    if description:
        sections.append(f"Description: {description}")

    sections.append("")

    # Include framework hints if available
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


def build_refinement_prompt(
    repo_name: str,
    file_contents: dict[str, str],
    candidate_files: list[str],
    max_to_select: int,
) -> str:
    """
    Build prompt for second-pass refinement selection.

    Args:
        repo_name: Repository name
        file_contents: Dict of already-read file paths to their contents
        candidate_files: List of candidate file paths to consider
        max_to_select: Maximum number of files to select

    Returns:
        Formatted prompt string for Claude
    """
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
