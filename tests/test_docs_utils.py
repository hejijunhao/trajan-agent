"""
Tests for documentation utilities.

Tests cover:
- Title extraction from markdown content
- Path to folder mapping
- Document type inference
- GitHub path generation
"""

import pytest

from app.services.docs.utils import (
    extract_title,
    generate_github_path,
    infer_doc_type,
    map_path_to_folder,
)


class TestExtractTitle:
    """Tests for title extraction from markdown."""

    def test_extract_h1_title(self) -> None:
        """Should extract H1 heading as title."""
        content = "# My Document Title\n\nSome content here."
        result = extract_title(content, "docs/readme.md")
        assert result == "My Document Title"

    def test_extract_h1_with_leading_whitespace(self) -> None:
        """Should extract H1 even with leading whitespace."""
        content = "\n\n# Document Title\n\nContent"
        result = extract_title(content, "doc.md")
        assert result == "Document Title"

    def test_extract_first_h1_only(self) -> None:
        """Should only extract the first H1."""
        content = "# First Title\n\n# Second Title\n\nContent"
        result = extract_title(content, "doc.md")
        assert result == "First Title"

    def test_fallback_to_filename(self) -> None:
        """Should fallback to filename when no H1 found."""
        content = "No heading here, just text."
        result = extract_title(content, "docs/my-document.md")
        assert result == "My Document"

    def test_fallback_handles_underscores(self) -> None:
        """Should convert underscores to spaces in fallback."""
        content = "No heading"
        result = extract_title(content, "docs/my_cool_document.md")
        assert result == "My Cool Document"

    def test_fallback_removes_extension(self) -> None:
        """Should remove .md extension in fallback."""
        content = ""
        result = extract_title(content, "README.md")
        assert result == "Readme"

    def test_ignores_h2_headings(self) -> None:
        """Should not use H2 headings as title."""
        content = "## This is H2\n\nSome text."
        result = extract_title(content, "document.md")
        assert result == "Document"

    def test_strips_whitespace_from_title(self) -> None:
        """Should strip whitespace from extracted title."""
        content = "#   Spaced Title   \n\nContent"
        result = extract_title(content, "doc.md")
        assert result == "Spaced Title"


class TestMapPathToFolder:
    """Tests for path to folder mapping."""

    def test_changelog_returns_none(self) -> None:
        """Changelog files should return None (root level)."""
        assert map_path_to_folder("CHANGELOG.md") is None
        assert map_path_to_folder("changelog.md") is None
        assert map_path_to_folder("docs/changelog.md") is None

    def test_changes_returns_none(self) -> None:
        """Changes/history files should return None."""
        assert map_path_to_folder("CHANGES.md") is None
        assert map_path_to_folder("HISTORY.md") is None

    def test_blueprints_folder(self) -> None:
        """Blueprint folder patterns should map to blueprints."""
        assert map_path_to_folder("docs/blueprints/overview.md") == "blueprints"
        assert map_path_to_folder("docs/overview/main.md") == "blueprints"
        assert map_path_to_folder("docs/architecture/design.md") == "blueprints"

    def test_plans_folder(self) -> None:
        """Plan folder patterns should map to plans."""
        assert map_path_to_folder("docs/plans/feature.md") == "plans"
        assert map_path_to_folder("docs/roadmap/2024.md") == "plans"
        assert map_path_to_folder("docs/planning/q1.md") == "plans"

    def test_executing_folder(self) -> None:
        """Executing folder patterns should map to executing."""
        assert map_path_to_folder("docs/executing/current.md") == "executing"
        assert map_path_to_folder("docs/in-progress/task.md") == "executing"
        assert map_path_to_folder("docs/wip/feature.md") == "executing"

    def test_completions_folder(self) -> None:
        """Completion folder patterns should map to completions."""
        assert map_path_to_folder("docs/completions/done.md") == "completions"
        assert map_path_to_folder("docs/completed/feature.md") == "completions"
        assert map_path_to_folder("docs/done/task.md") == "completions"
        assert map_path_to_folder("docs/finished/work.md") == "completions"

    def test_completions_with_date(self) -> None:
        """Completion paths with dates should preserve date."""
        result = map_path_to_folder("docs/completions/2024-01-15/feature.md")
        assert result == "completions/2024-01-15"

    def test_archive_folder(self) -> None:
        """Archive folder patterns should map to archive."""
        assert map_path_to_folder("docs/archive/old.md") == "archive"
        assert map_path_to_folder("docs/old/legacy.md") == "archive"
        assert map_path_to_folder("docs/deprecated/feature.md") == "archive"

    def test_default_docs_folder(self) -> None:
        """Unrecognized docs/ paths should map to blueprints."""
        assert map_path_to_folder("docs/random.md") == "blueprints"
        assert map_path_to_folder("docs/some/nested/doc.md") == "blueprints"

    def test_non_docs_path(self) -> None:
        """Non-docs paths without patterns should return None."""
        assert map_path_to_folder("src/readme.md") is None
        assert map_path_to_folder("random.md") is None

    # Filename-based classification tests
    def test_plan_filename_patterns(self) -> None:
        """Files with plan indicators in filename should map to plans."""
        # Suffix patterns
        assert map_path_to_folder("docs/feature-plan.md") == "plans"
        assert map_path_to_folder("docs/auth_plan.md") == "plans"
        # Prefix patterns
        assert map_path_to_folder("docs/plan-feature.md") == "plans"
        # Implementation plans
        assert map_path_to_folder("docs/auth-implementation.md") == "plans"
        # Phase documents
        assert map_path_to_folder("docs/phase-6-ui-controls.md") == "plans"
        assert map_path_to_folder("docs/phase_1_setup.md") == "plans"
        # Roadmap/proposal patterns
        assert map_path_to_folder("docs/q1-roadmap.md") == "plans"
        assert map_path_to_folder("docs/feature-proposal.md") == "plans"

    def test_completion_filename_patterns(self) -> None:
        """Files with completion indicators in filename should map to completions."""
        assert map_path_to_folder("docs/feature-completion.md") == "completions"
        assert map_path_to_folder("docs/auth-report.md") == "completions"
        assert map_path_to_folder("docs/task_completed.md") == "completions"

    def test_folder_patterns_take_precedence(self) -> None:
        """Explicit folder structure should override filename patterns."""
        # A plan file in blueprints folder stays in blueprints
        assert map_path_to_folder("docs/blueprints/implementation-plan.md") == "blueprints"
        # A file with "plan" in name but in archive folder stays in archive
        assert map_path_to_folder("docs/archive/old-plan.md") == "archive"


class TestInferDocType:
    """Tests for document type inference."""

    def test_changelog_type(self) -> None:
        """Changelog paths should return changelog type."""
        assert infer_doc_type("CHANGELOG.md") == "changelog"
        assert infer_doc_type("docs/changelog.md") == "changelog"
        assert infer_doc_type("CHANGES.md") == "changelog"
        assert infer_doc_type("HISTORY.md") == "changelog"

    def test_architecture_type(self) -> None:
        """Architecture paths should return architecture type."""
        assert infer_doc_type("docs/architecture.md") == "architecture"
        assert infer_doc_type("docs/architecture/overview.md") == "architecture"

    def test_plan_type(self) -> None:
        """Plan paths should return plan type."""
        assert infer_doc_type("docs/plan.md") == "plan"
        assert infer_doc_type("docs/roadmap.md") == "plan"
        assert infer_doc_type("docs/proposal.md") == "plan"

    def test_readme_type(self) -> None:
        """README paths should return blueprint type."""
        assert infer_doc_type("README.md") == "blueprint"
        assert infer_doc_type("docs/readme.md") == "blueprint"

    def test_api_type(self) -> None:
        """API paths should return architecture type."""
        assert infer_doc_type("docs/api.md") == "architecture"
        assert infer_doc_type("docs/api/endpoints.md") == "architecture"

    def test_guide_type(self) -> None:
        """Guide/tutorial paths should return note type."""
        assert infer_doc_type("docs/guide.md") == "note"
        assert infer_doc_type("docs/tutorial.md") == "note"

    def test_default_type(self) -> None:
        """Unknown paths should return blueprint type."""
        assert infer_doc_type("docs/random.md") == "blueprint"
        assert infer_doc_type("docs/overview.md") == "blueprint"


class TestGenerateGitHubPath:
    """Tests for GitHub path generation."""

    def test_changelog_path(self) -> None:
        """Changelog documents should go to docs/changelog.md."""
        result = generate_github_path("Changelog", None, "changelog")
        assert result == "docs/changelog.md"

    def test_root_document(self) -> None:
        """Documents without folder should go to docs/."""
        result = generate_github_path("My Document", None, "blueprint")
        assert result == "docs/my-document.md"

    def test_folder_path(self) -> None:
        """Documents with folder should include folder in path."""
        result = generate_github_path("Feature Plan", "plans", "plan")
        assert result == "docs/plans/feature-plan.md"

    def test_nested_folder(self) -> None:
        """Documents with nested folder should work."""
        result = generate_github_path("Done Task", "completions/2024-01-15", "plan")
        assert result == "docs/completions/2024-01-15/done-task.md"

    def test_slugifies_title(self) -> None:
        """Should slugify the title properly."""
        result = generate_github_path("My Cool Document!", "blueprints", "blueprint")
        assert result == "docs/blueprints/my-cool-document.md"

    def test_removes_special_characters(self) -> None:
        """Should remove special characters from slug."""
        result = generate_github_path("Feature: Add Auth (v2)", "plans", "plan")
        assert result == "docs/plans/feature-add-auth-v2.md"

    def test_empty_title_fallback(self) -> None:
        """Empty title should fallback to 'untitled'."""
        result = generate_github_path("", "blueprints", "blueprint")
        assert result == "docs/blueprints/untitled.md"

    def test_collapses_multiple_dashes(self) -> None:
        """Should collapse multiple dashes into one."""
        result = generate_github_path("My - - Document", "plans", "plan")
        assert result == "docs/plans/my-document.md"
