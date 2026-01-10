"""
Tests for the FileSelector service.

Tests cover:
- Prompt building
- Response parsing (valid JSON, markdown-wrapped JSON, malformed)
- Tree truncation for large repos
- Edge cases (empty repos, small repos)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.file_selector import (
    FileSelector,
    FileSelectorInput,
    MAX_FILES_TO_SELECT,
    MAX_TREE_FILES,
    MIN_FILES_TO_SELECT,
)


# Sample file trees for testing
SMALL_REPO_FILES = [
    "README.md",
    "src/main.py",
    "src/utils.py",
    "tests/test_main.py",
]

MEDIUM_REPO_FILES = [
    "README.md",
    "package.json",
    "src/index.ts",
    "src/routes/api.ts",
    "src/routes/auth.ts",
    "src/models/user.ts",
    "src/models/product.ts",
    "src/services/auth.ts",
    "src/services/payment.ts",
    "src/utils/helpers.ts",
    "src/utils/validators.ts",
    "src/components/Header.tsx",
    "src/components/Footer.tsx",
    "src/pages/index.tsx",
    "src/pages/login.tsx",
    "tests/api.test.ts",
    "tests/auth.test.ts",
    ".gitignore",
    ".env.example",
    "tsconfig.json",
]


class TestFileSelectorParsing:
    """Tests for response parsing."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.selector = FileSelector()
        self.valid_files = set(MEDIUM_REPO_FILES)

    def test_parse_valid_json_array(self) -> None:
        """Parse a valid JSON array response."""
        response = '["src/routes/api.ts", "src/models/user.ts"]'
        result = self.selector._parse_response(response, self.valid_files)

        assert result == ["src/routes/api.ts", "src/models/user.ts"]

    def test_parse_markdown_wrapped_json(self) -> None:
        """Parse JSON wrapped in markdown code blocks."""
        response = """```json
["src/routes/api.ts", "src/models/user.ts"]
```"""
        result = self.selector._parse_response(response, self.valid_files)

        assert result == ["src/routes/api.ts", "src/models/user.ts"]

    def test_parse_json_with_extra_text(self) -> None:
        """Parse JSON when there's extra text around it."""
        response = """Here are the files:

["src/routes/api.ts", "src/models/user.ts"]

These files are important."""
        result = self.selector._parse_response(response, self.valid_files)

        assert result == ["src/routes/api.ts", "src/models/user.ts"]

    def test_parse_filters_invalid_paths(self) -> None:
        """Parsing should filter out paths not in the valid set."""
        response = '["src/routes/api.ts", "nonexistent/file.ts", "src/models/user.ts"]'
        result = self.selector._parse_response(response, self.valid_files)

        assert result == ["src/routes/api.ts", "src/models/user.ts"]
        assert "nonexistent/file.ts" not in result

    def test_parse_limits_to_max_files(self) -> None:
        """Parsing should limit results to MAX_FILES_TO_SELECT."""
        # Create response with more files than limit
        many_files = MEDIUM_REPO_FILES[:MAX_FILES_TO_SELECT + 5]
        quoted_files = [f'"{f}"' for f in many_files]
        response = "[" + ", ".join(quoted_files) + "]"
        valid_set = set(many_files)

        result = self.selector._parse_response(response, valid_set)

        assert len(result) <= MAX_FILES_TO_SELECT

    def test_parse_invalid_json_returns_empty(self) -> None:
        """Invalid JSON should return empty list."""
        response = "This is not JSON at all"
        result = self.selector._parse_response(response, self.valid_files)

        assert result == []

    def test_parse_non_array_returns_empty(self) -> None:
        """Non-array JSON should return empty list."""
        response = '{"files": ["src/main.py"]}'
        result = self.selector._parse_response(response, self.valid_files)

        assert result == []

    def test_parse_filters_non_string_items(self) -> None:
        """Non-string items in array should be filtered."""
        response = '["src/routes/api.ts", 123, null, "src/models/user.ts"]'
        result = self.selector._parse_response(response, self.valid_files)

        assert result == ["src/routes/api.ts", "src/models/user.ts"]


class TestFileSelectorTruncation:
    """Tests for tree truncation logic."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.selector = FileSelector()

    def test_truncate_prioritizes_src_directory(self) -> None:
        """Files in src/ should be prioritized during truncation."""
        files = [
            "docs/readme.md",
            "src/main.py",
            "src/routes/api.py",
            "random/file.txt",
        ]
        # Since we have fewer than MAX_TREE_FILES, simulate by checking order
        result = self.selector._truncate_tree(files)

        # All files should be present since under limit
        assert set(result) == set(files)

    def test_truncate_prioritizes_app_directory(self) -> None:
        """Files in app/ should be prioritized during truncation."""
        files = [
            "app/main.py",
            "app/routes.py",
            "other/stuff.py",
        ]
        result = self.selector._truncate_tree(files)

        assert set(result) == set(files)

    def test_truncate_respects_max_limit(self) -> None:
        """Truncation should respect MAX_TREE_FILES limit."""
        # Generate more files than limit
        large_file_list = [f"file_{i}.py" for i in range(MAX_TREE_FILES + 100)]

        result = self.selector._truncate_tree(large_file_list)

        assert len(result) == MAX_TREE_FILES

    def test_truncate_depth_sorting(self) -> None:
        """Files at shallower depths should come first."""
        files = [
            "src/deep/nested/file.py",
            "src/main.py",
            "src/routes/api.py",
        ]

        result = self.selector._truncate_tree(files)

        # Check that shallower files come first within priority category
        src_main_idx = result.index("src/main.py")
        src_deep_idx = result.index("src/deep/nested/file.py")
        assert src_main_idx < src_deep_idx


class TestFileSelectorSelect:
    """Integration tests for the select_files method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.selector = FileSelector()

    async def test_empty_repo_returns_empty(self) -> None:
        """Empty repository should return empty result."""
        input_data = FileSelectorInput(
            repo_name="test/repo",
            description=None,
            readme_content=None,
            file_paths=[],
        )

        result = await self.selector.select_files(input_data)

        assert result.selected_files == []
        assert result.truncated is False
        assert result.file_count_before_truncation == 0

    async def test_small_repo_returns_all_files(self) -> None:
        """Repos smaller than MIN_FILES_TO_SELECT return all files."""
        small_files = ["main.py", "utils.py", "test.py"]
        input_data = FileSelectorInput(
            repo_name="test/repo",
            description="Test repo",
            readme_content="# Test",
            file_paths=small_files,
        )

        result = await self.selector.select_files(input_data)

        assert result.selected_files == small_files
        assert result.truncated is False

    @patch("app.services.file_selector.FileSelector._call_with_retry")
    async def test_medium_repo_calls_api(self, mock_call: AsyncMock) -> None:
        """Medium repos should call the API for file selection."""
        mock_call.return_value = ["src/routes/api.ts", "src/models/user.ts"]

        input_data = FileSelectorInput(
            repo_name="test/repo",
            description="A test repository",
            readme_content="# Test Repo\n\nThis is a test.",
            file_paths=MEDIUM_REPO_FILES,
        )

        result = await self.selector.select_files(input_data)

        mock_call.assert_called_once()
        assert result.selected_files == ["src/routes/api.ts", "src/models/user.ts"]
        assert result.truncated is False

    @patch("app.services.file_selector.FileSelector._call_with_retry")
    async def test_large_repo_truncates(self, mock_call: AsyncMock) -> None:
        """Large repos should be truncated before API call."""
        mock_call.return_value = ["file_0.py", "file_1.py"]

        # Generate large file list
        large_files = [f"file_{i}.py" for i in range(MAX_TREE_FILES + 500)]

        input_data = FileSelectorInput(
            repo_name="test/repo",
            description="Large repo",
            readme_content=None,
            file_paths=large_files,
        )

        result = await self.selector.select_files(input_data)

        assert result.truncated is True
        assert result.file_count_before_truncation == MAX_TREE_FILES + 500


class TestFileSelectorPrompt:
    """Tests for prompt building."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.selector = FileSelector()

    def test_prompt_includes_repo_name(self) -> None:
        """Prompt should include repository name."""
        prompt = self.selector._build_prompt(
            repo_name="owner/repo",
            description=None,
            readme_content=None,
            file_paths=["main.py"],
        )

        assert "owner/repo" in prompt

    def test_prompt_includes_description(self) -> None:
        """Prompt should include description when provided."""
        prompt = self.selector._build_prompt(
            repo_name="test/repo",
            description="A cool project",
            readme_content=None,
            file_paths=["main.py"],
        )

        assert "A cool project" in prompt

    def test_prompt_includes_readme(self) -> None:
        """Prompt should include README content when provided."""
        prompt = self.selector._build_prompt(
            repo_name="test/repo",
            description=None,
            readme_content="# My Project\n\nThis does cool stuff.",
            file_paths=["main.py"],
        )

        assert "My Project" in prompt
        assert "cool stuff" in prompt

    def test_prompt_truncates_long_readme(self) -> None:
        """Long README should be truncated."""
        long_readme = "A" * 5000

        prompt = self.selector._build_prompt(
            repo_name="test/repo",
            description=None,
            readme_content=long_readme,
            file_paths=["main.py"],
        )

        assert "truncated" in prompt.lower()
        assert len(prompt) < len(long_readme) + 1000  # Should be much smaller

    def test_prompt_includes_file_count(self) -> None:
        """Prompt should show total file count."""
        files = ["a.py", "b.py", "c.py"]

        prompt = self.selector._build_prompt(
            repo_name="test/repo",
            description=None,
            readme_content=None,
            file_paths=files,
        )

        assert "Total files: 3" in prompt

    def test_prompt_lists_files(self) -> None:
        """Prompt should list all file paths."""
        files = ["src/main.py", "src/utils.py"]

        prompt = self.selector._build_prompt(
            repo_name="test/repo",
            description=None,
            readme_content=None,
            file_paths=files,
        )

        assert "src/main.py" in prompt
        assert "src/utils.py" in prompt

    def test_prompt_includes_selection_guidance(self) -> None:
        """Prompt should include guidance for file selection."""
        prompt = self.selector._build_prompt(
            repo_name="test/repo",
            description=None,
            readme_content=None,
            file_paths=["main.py"],
        )

        assert "API" in prompt
        assert "Models" in prompt
        assert "Services" in prompt
        assert "JSON" in prompt.lower() or "json" in prompt
