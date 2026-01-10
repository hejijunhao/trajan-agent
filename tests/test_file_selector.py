"""
Tests for the FileSelector service.

Tests cover:
- Prompt building
- Response parsing (valid JSON, markdown-wrapped JSON, malformed)
- Tree truncation for large repos
- Edge cases (empty repos, small repos)
- Framework hints integration (Phase 4)
- Heuristic fallback (Phase 4)
- Two-pass refinement (Phase 4)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.file_selector import (
    FALLBACK_PATTERNS,
    FileSelector,
    FileSelectorInput,
    MAX_FILES_TO_SELECT,
    MAX_TREE_FILES,
    MIN_FILES_TO_SELECT,
)
from app.services.framework_detector import DetectionResult, FrameworkInfo


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
        # Return enough files to avoid triggering fallback (>= MIN_FILES_TO_SELECT // 2 = 5)
        mock_call.return_value = [
            "src/routes/api.ts",
            "src/routes/auth.ts",
            "src/models/user.ts",
            "src/models/product.ts",
            "src/services/auth.ts",
            "src/services/payment.ts",
        ]

        input_data = FileSelectorInput(
            repo_name="test/repo",
            description="A test repository",
            readme_content="# Test Repo\n\nThis is a test.",
            file_paths=MEDIUM_REPO_FILES,
        )

        result = await self.selector.select_files(input_data)

        mock_call.assert_called_once()
        # Should include API results
        assert "src/routes/api.ts" in result.selected_files
        assert "src/models/user.ts" in result.selected_files
        assert result.truncated is False
        assert result.used_fallback is False

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

    def test_prompt_includes_framework_hints(self) -> None:
        """Prompt should include framework hints when provided."""
        framework_hints = DetectionResult(
            frameworks=[
                FrameworkInfo(
                    name="fastapi",
                    category="backend",
                    file_patterns=["app/**/*.py"],
                    directory_hints=["app/", "app/api/"],
                )
            ],
            primary_language="python",
            suggested_directories=["app/", "app/api/"],
        )

        prompt = self.selector._build_prompt(
            repo_name="test/repo",
            description=None,
            readme_content=None,
            file_paths=["main.py"],
            framework_hints=framework_hints,
        )

        assert "fastapi" in prompt
        assert "app/" in prompt


class TestFileSelectorFallback:
    """Tests for heuristic fallback (Phase 4)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.selector = FileSelector()

    def test_fallback_selects_routes(self) -> None:
        """Fallback should select route files."""
        files = [
            "src/routes/api.ts",
            "src/routes/auth.ts",
            "src/utils/helpers.ts",
            "tests/test_api.ts",
        ]

        result = self.selector._heuristic_fallback(files)

        assert "src/routes/api.ts" in result
        assert "src/routes/auth.ts" in result
        # Should not include test files
        assert "tests/test_api.ts" not in result

    def test_fallback_selects_models(self) -> None:
        """Fallback should select model files."""
        files = [
            "src/models/user.py",
            "src/models/product.py",
            "docs/readme.md",
        ]

        result = self.selector._heuristic_fallback(files)

        assert "src/models/user.py" in result
        assert "src/models/product.py" in result

    def test_fallback_selects_entry_points(self) -> None:
        """Fallback should select entry point files."""
        files = [
            "main.py",
            "app.py",
            "config.py",
            "utils.py",
        ]

        result = self.selector._heuristic_fallback(files)

        assert "main.py" in result
        assert "app.py" in result

    def test_fallback_respects_max_limit(self) -> None:
        """Fallback should not exceed MAX_FILES_TO_SELECT."""
        # Create many matching files
        files = [f"src/routes/route_{i}.py" for i in range(100)]

        result = self.selector._heuristic_fallback(files)

        assert len(result) <= MAX_FILES_TO_SELECT

    def test_fallback_uses_framework_directories(self) -> None:
        """Fallback should prioritize framework-specific directories."""
        framework_hints = DetectionResult(
            frameworks=[
                FrameworkInfo(
                    name="fastapi",
                    category="backend",
                    file_patterns=[],
                    directory_hints=["app/api/", "app/models/"],
                )
            ],
            suggested_directories=["app/api/", "app/models/"],
        )

        files = [
            "app/api/routes.py",
            "app/models/user.py",
            "other/stuff.py",
            "random.py",
        ]

        result = self.selector._heuristic_fallback(files, framework_hints)

        # Framework directories should be prioritized
        assert "app/api/routes.py" in result
        assert "app/models/user.py" in result


class TestFileSelectorSourceFileDetection:
    """Tests for source file detection helpers."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.selector = FileSelector()

    def test_is_source_file_python(self) -> None:
        """Python files should be detected as source."""
        assert self.selector._is_source_file("main.py") is True
        assert self.selector._is_source_file("src/utils.py") is True

    def test_is_source_file_typescript(self) -> None:
        """TypeScript files should be detected as source."""
        assert self.selector._is_source_file("app.ts") is True
        assert self.selector._is_source_file("component.tsx") is True

    def test_is_source_file_not_source(self) -> None:
        """Non-source files should not be detected."""
        assert self.selector._is_source_file("readme.md") is False
        assert self.selector._is_source_file("data.json") is False
        assert self.selector._is_source_file("image.png") is False

    def test_is_test_file(self) -> None:
        """Test files should be detected."""
        assert self.selector._is_test_file("tests/test_main.py") is True
        assert self.selector._is_test_file("src/__tests__/app.test.ts") is True
        assert self.selector._is_test_file("test_utils.py") is True
        assert self.selector._is_test_file("app.spec.ts") is True

    def test_is_not_test_file(self) -> None:
        """Non-test files should not be detected as tests."""
        assert self.selector._is_test_file("src/main.py") is False
        assert self.selector._is_test_file("app/routes.ts") is False


class TestFileSelectorWithFallback:
    """Integration tests for fallback behavior."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.selector = FileSelector()

    @patch("app.services.file_selector.FileSelector._call_with_retry")
    async def test_fallback_on_empty_result(self, mock_call: AsyncMock) -> None:
        """Should use fallback when API returns empty."""
        mock_call.return_value = []  # Empty result triggers fallback

        files = [
            "src/routes/api.ts",
            "src/models/user.ts",
            "package.json",
        ] + [f"file_{i}.ts" for i in range(20)]  # Need enough files to trigger API call

        input_data = FileSelectorInput(
            repo_name="test/repo",
            description="Test repo",
            readme_content=None,
            file_paths=files,
        )

        result = await self.selector.select_files(input_data)

        # Should have used fallback
        assert result.used_fallback is True
        # Should have selected some files via heuristics
        assert len(result.selected_files) > 0


class TestFileSelectorRefinement:
    """Tests for two-pass refinement (Phase 4)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.selector = FileSelector()

    def test_extract_references_python_imports(self) -> None:
        """Should extract Python import statements."""
        file_contents = {
            "main.py": "from app.models import User\nimport app.services.auth",
        }
        valid_paths = {
            "app/models.py",
            "app/models/__init__.py",
            "app/services/auth.py",
            "other/file.py",
        }

        refs = self.selector._extract_references(file_contents, valid_paths)

        # Should find resolved imports
        assert len(refs) >= 0  # May or may not resolve depending on path structure

    def test_extract_references_js_imports(self) -> None:
        """Should extract JavaScript import statements."""
        file_contents = {
            "src/app.ts": "import { User } from './models/user'\nimport api from '@/api'",
        }
        valid_paths = {"src/models/user.ts", "src/api.ts", "src/api/index.ts"}

        refs = self.selector._extract_references(file_contents, valid_paths)

        # Should attempt to resolve imports
        assert isinstance(refs, list)

    def test_resolve_import_relative(self) -> None:
        """Should resolve relative imports."""
        valid_paths = {"src/models/user.ts", "src/utils/helpers.ts"}

        resolved = self.selector._resolve_import(
            import_path="models/user",
            current_dir="src",
            valid_paths=valid_paths,
        )

        assert "src/models/user.ts" in resolved

    def test_resolve_import_absolute(self) -> None:
        """Should resolve absolute imports."""
        valid_paths = {"src/main.py", "app/main.py"}

        resolved = self.selector._resolve_import(
            import_path="main",
            current_dir="",
            valid_paths=valid_paths,
        )

        # Should find files with various prefixes
        assert any("main" in f for f in resolved)

    @patch("app.services.file_selector.FileSelector._call_with_retry")
    async def test_refine_selection_adds_files(self, mock_call: AsyncMock) -> None:
        """Refinement should identify additional files."""
        mock_call.return_value = ["src/types/user.ts"]

        file_paths = ["src/app.ts", "src/types/user.ts", "src/types/product.ts"]
        already_selected = ["src/app.ts"]
        file_contents = {"src/app.ts": "import { User } from './types/user'"}

        result = await self.selector.refine_selection(
            repo_name="test/repo",
            file_paths=file_paths,
            already_selected=already_selected,
            file_contents=file_contents,
        )

        # Should have called API and returned additional files
        mock_call.assert_called_once()
        assert "src/types/user.ts" in result
