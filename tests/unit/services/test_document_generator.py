"""
Tests for DocumentGenerator service.

Tests cover:
- Model selection based on document type
- File extraction from codebase context
- Prompt building for different document types
- Response parsing
- Result types
"""

from unittest.mock import MagicMock

import anthropic

from app.services.docs.document_generator import (
    COMPLEX_DOC_TYPES,
    MODEL_OPUS,
    MODEL_SONNET,
    DocumentGenerator,
)
from app.services.docs.types import (
    BatchGeneratorResult,
    CodebaseContext,
    FileContent,
    GeneratorResult,
    PlannedDocument,
    TechStack,
)


def make_tech_stack(
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
) -> TechStack:
    """Helper to create a TechStack with defaults."""
    return TechStack(
        languages=languages or [],
        frameworks=frameworks or [],
        databases=[],
        infrastructure=[],
        package_managers=[],
    )


def make_codebase_context(
    key_files: list[FileContent] | None = None,
    tech_stack: TechStack | None = None,
    patterns: list[str] | None = None,
) -> CodebaseContext:
    """Helper to create a CodebaseContext with defaults."""
    return CodebaseContext(
        repositories=[],
        combined_tech_stack=tech_stack or make_tech_stack(),
        all_key_files=key_files or [],
        all_models=[],
        all_endpoints=[],
        detected_patterns=patterns or [],
        total_files=10,
        total_tokens=1000,
        errors=[],
    )


def make_planned_document(
    title: str = "Test Document",
    doc_type: str = "overview",
    purpose: str = "Test purpose",
    key_topics: list[str] | None = None,
    source_files: list[str] | None = None,
    priority: int = 1,
    folder: str = "blueprints",
) -> PlannedDocument:
    """Helper to create a PlannedDocument with defaults."""
    return PlannedDocument(
        title=title,
        doc_type=doc_type,
        purpose=purpose,
        key_topics=key_topics or [],
        source_files=source_files or [],
        priority=priority,
        folder=folder,
    )


class TestModelSelection:
    """Tests for model selection based on document type."""

    def setup_method(self) -> None:
        """Create generator instance for testing."""
        self.generator = DocumentGenerator.__new__(DocumentGenerator)

    def test_architecture_uses_opus(self) -> None:
        """Architecture docs should use Opus for deeper reasoning."""
        assert self.generator._select_model("architecture") == MODEL_OPUS

    def test_concept_uses_opus(self) -> None:
        """Concept docs should use Opus for deeper reasoning."""
        assert self.generator._select_model("concept") == MODEL_OPUS

    def test_overview_uses_sonnet(self) -> None:
        """Overview docs should use Sonnet."""
        assert self.generator._select_model("overview") == MODEL_SONNET

    def test_guide_uses_sonnet(self) -> None:
        """Guide docs should use Sonnet."""
        assert self.generator._select_model("guide") == MODEL_SONNET

    def test_reference_uses_sonnet(self) -> None:
        """Reference docs should use Sonnet."""
        assert self.generator._select_model("reference") == MODEL_SONNET

    def test_complex_doc_types_constant(self) -> None:
        """Complex doc types constant should have expected values."""
        assert "architecture" in COMPLEX_DOC_TYPES
        assert "concept" in COMPLEX_DOC_TYPES
        assert len(COMPLEX_DOC_TYPES) == 2


class TestFileExtraction:
    """Tests for extracting relevant files from codebase context."""

    def setup_method(self) -> None:
        """Create generator instance for testing."""
        self.generator = DocumentGenerator.__new__(DocumentGenerator)

    def test_exact_path_match(self) -> None:
        """Should match files by exact path."""
        files = [
            FileContent("README.md", "# Project", 100, 1, 25),
            FileContent("app/main.py", "print('hello')", 200, 2, 50),
        ]
        context = make_codebase_context(key_files=files)

        result = self.generator._extract_relevant_files(
            ["README.md"],
            context.all_key_files,
        )

        assert len(result) == 1
        assert result[0].path == "README.md"

    def test_pattern_match(self) -> None:
        """Should match files containing the pattern."""
        files = [
            FileContent("backend/app/api/users.py", "def get_users():", 300, 2, 75),
            FileContent("backend/app/api/products.py", "def get_products():", 300, 2, 75),
            FileContent("frontend/src/App.tsx", "export default App", 200, 2, 50),
        ]
        context = make_codebase_context(key_files=files)

        result = self.generator._extract_relevant_files(
            ["backend/app/api/"],
            context.all_key_files,
        )

        assert len(result) == 2
        paths = [f.path for f in result]
        assert "backend/app/api/users.py" in paths
        assert "backend/app/api/products.py" in paths

    def test_filename_match(self) -> None:
        """Should match by filename when path doesn't match."""
        files = [
            FileContent("src/components/Button.tsx", "export const Button", 150, 2, 40),
            FileContent("src/components/Form.tsx", "export const Form", 200, 2, 50),
        ]
        context = make_codebase_context(key_files=files)

        result = self.generator._extract_relevant_files(
            ["Button.tsx"],
            context.all_key_files,
        )

        assert len(result) == 1
        assert result[0].path == "src/components/Button.tsx"

    def test_fallback_to_tier_1_files(self) -> None:
        """Should include tier 1 files if no specific matches found."""
        files = [
            FileContent("README.md", "# Project", 100, 1, 25),
            FileContent("package.json", '{"name": "test"}', 150, 1, 40),
            FileContent("src/app.ts", "const app = new App()", 200, 2, 50),
        ]
        context = make_codebase_context(key_files=files)

        result = self.generator._extract_relevant_files(
            ["nonexistent.py"],  # Won't match anything
            context.all_key_files,
        )

        # Should fall back to tier 1 files
        assert len(result) == 2
        tiers = [f.tier for f in result]
        assert all(t == 1 for t in tiers)

    def test_respects_token_budget(self) -> None:
        """Should not exceed token budget."""
        # Create files that would exceed the 50k token budget
        files = [FileContent(f"file{i}.py", "x" * 10000, 10000, 1, 30000) for i in range(5)]
        context = make_codebase_context(key_files=files)

        result = self.generator._extract_relevant_files(
            ["file0.py", "file1.py", "file2.py"],
            context.all_key_files,
        )

        # Should stop before exceeding budget (50k tokens)
        total_tokens = sum(f.token_estimate for f in result)
        assert total_tokens <= 50000


class TestPromptBuilding:
    """Tests for prompt construction."""

    def setup_method(self) -> None:
        """Create generator instance for testing."""
        self.generator = DocumentGenerator.__new__(DocumentGenerator)

    def test_prompt_includes_document_spec(self) -> None:
        """Prompt should include document specification."""
        planned_doc = make_planned_document(
            title="API Reference",
            doc_type="reference",
            purpose="Document all endpoints",
        )
        context = make_codebase_context()

        prompt = self.generator._build_prompt(planned_doc, [], context)

        assert "API Reference" in prompt
        assert "reference" in prompt
        assert "Document all endpoints" in prompt

    def test_prompt_includes_key_topics(self) -> None:
        """Prompt should include key topics to cover."""
        planned_doc = make_planned_document(
            key_topics=["Authentication", "Error handling", "Rate limits"],
        )
        context = make_codebase_context()

        prompt = self.generator._build_prompt(planned_doc, [], context)

        assert "Authentication" in prompt
        assert "Error handling" in prompt
        assert "Rate limits" in prompt

    def test_prompt_includes_tech_stack(self) -> None:
        """Prompt should include technology context."""
        tech = make_tech_stack(
            languages=["Python", "TypeScript"],
            frameworks=["FastAPI", "Next.js"],
        )
        context = make_codebase_context(tech_stack=tech)
        planned_doc = make_planned_document()

        prompt = self.generator._build_prompt(planned_doc, [], context)

        assert "Python" in prompt
        assert "TypeScript" in prompt
        assert "FastAPI" in prompt
        assert "Next.js" in prompt

    def test_prompt_includes_source_files(self) -> None:
        """Prompt should include source file contents."""
        files = [
            FileContent("app/main.py", "from fastapi import FastAPI", 100, 1, 25),
        ]
        context = make_codebase_context()
        planned_doc = make_planned_document()

        prompt = self.generator._build_prompt(planned_doc, files, context)

        assert "app/main.py" in prompt
        assert "from fastapi import FastAPI" in prompt

    def test_prompt_includes_detected_patterns(self) -> None:
        """Prompt should include architecture patterns."""
        context = make_codebase_context(patterns=["REST API", "Monorepo"])
        planned_doc = make_planned_document()

        prompt = self.generator._build_prompt(planned_doc, [], context)

        assert "REST API" in prompt
        assert "Monorepo" in prompt


class TestTypeInstructions:
    """Tests for document type-specific instructions."""

    def setup_method(self) -> None:
        """Create generator instance for testing."""
        self.generator = DocumentGenerator.__new__(DocumentGenerator)

    def test_overview_instructions(self) -> None:
        """Overview docs should have appropriate instructions."""
        planned_doc = make_planned_document(doc_type="overview")
        instructions = self.generator._get_type_instructions(planned_doc)
        text = "\n".join(instructions)

        assert "comprehensive project overview" in text.lower()
        assert "what this software does" in text.lower()

    def test_architecture_instructions(self) -> None:
        """Architecture docs should have technical instructions."""
        planned_doc = make_planned_document(doc_type="architecture")
        instructions = self.generator._get_type_instructions(planned_doc)
        text = "\n".join(instructions)

        assert "system design" in text.lower()
        assert "data flows" in text.lower()

    def test_guide_instructions(self) -> None:
        """Guide docs should have how-to instructions."""
        planned_doc = make_planned_document(doc_type="guide")
        instructions = self.generator._get_type_instructions(planned_doc)
        text = "\n".join(instructions)

        assert "step-by-step" in text.lower()
        assert "code examples" in text.lower()

    def test_reference_instructions(self) -> None:
        """Reference docs should have factual instructions."""
        planned_doc = make_planned_document(doc_type="reference")
        instructions = self.generator._get_type_instructions(planned_doc)
        text = "\n".join(instructions)

        assert "complete" in text.lower()
        assert "accurate" in text.lower()

    def test_concept_instructions(self) -> None:
        """Concept docs should have educational instructions."""
        planned_doc = make_planned_document(doc_type="concept")
        instructions = self.generator._get_type_instructions(planned_doc)
        text = "\n".join(instructions)

        assert "mental model" in text.lower()
        assert "understanding" in text.lower()


class TestToolSchema:
    """Tests for Claude tool schema."""

    def setup_method(self) -> None:
        """Create generator instance for testing."""
        self.generator = DocumentGenerator.__new__(DocumentGenerator)

    def test_tool_schema_structure(self) -> None:
        """Tool schema should have correct structure."""
        planned_doc = make_planned_document(title="Test Doc", doc_type="overview")
        schema = self.generator._build_tool_schema(planned_doc)

        assert schema["name"] == "save_document"
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"

    def test_tool_schema_requires_content(self) -> None:
        """Tool schema should require content field."""
        planned_doc = make_planned_document()
        schema = self.generator._build_tool_schema(planned_doc)

        assert "content" in schema["input_schema"]["required"]

    def test_tool_schema_includes_title_in_description(self) -> None:
        """Tool schema should mention the document title."""
        planned_doc = make_planned_document(title="Getting Started Guide")
        schema = self.generator._build_tool_schema(planned_doc)
        content_desc = schema["input_schema"]["properties"]["content"]["description"]

        assert "Getting Started Guide" in content_desc


class TestResponseParsing:
    """Tests for parsing Claude responses."""

    def setup_method(self) -> None:
        """Create generator instance for testing."""
        self.generator = DocumentGenerator.__new__(DocumentGenerator)

    def _make_tool_use_response(self, content: str) -> anthropic.types.Message:
        """Create a mock Message with tool_use block."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "save_document"
        tool_use_block.input = {"content": content}

        message = MagicMock(spec=anthropic.types.Message)
        message.content = [tool_use_block]
        return message

    def test_parse_valid_response(self) -> None:
        """Should correctly parse a valid Claude response."""
        content = "# Getting Started\n\nWelcome to the project."
        response = self._make_tool_use_response(content)
        planned_doc = make_planned_document(title="Getting Started")

        result = self.generator._parse_response(response, planned_doc)

        assert result == content

    def test_parse_fallback_on_missing_content(self) -> None:
        """Should return fallback content if content is missing."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "save_document"
        tool_use_block.input = {}  # Missing content

        message = MagicMock(spec=anthropic.types.Message)
        message.content = [tool_use_block]

        planned_doc = make_planned_document(title="Test Doc")
        result = self.generator._parse_response(message, planned_doc)

        assert "Test Doc" in result
        assert "failed" in result.lower()

    def test_parse_fallback_on_no_tool_use(self) -> None:
        """Should return fallback if no tool_use block."""
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I cannot generate this document"

        message = MagicMock(spec=anthropic.types.Message)
        message.content = [text_block]

        planned_doc = make_planned_document(title="My Doc")
        result = self.generator._parse_response(message, planned_doc)

        assert "My Doc" in result
        assert "failed" in result.lower()


class TestGeneratorResultType:
    """Tests for GeneratorResult dataclass."""

    def test_successful_result(self) -> None:
        """Should create successful GeneratorResult."""
        result = GeneratorResult(document=None, success=True)

        assert result.success is True
        assert result.error is None

    def test_failed_result(self) -> None:
        """Should create failed GeneratorResult with error."""
        result = GeneratorResult(
            document=None,
            success=False,
            error="API timeout",
        )

        assert result.success is False
        assert result.error == "API timeout"


class TestBatchGeneratorResultType:
    """Tests for BatchGeneratorResult dataclass."""

    def test_empty_result(self) -> None:
        """Should create empty BatchGeneratorResult."""
        result = BatchGeneratorResult()

        assert result.documents == []
        assert result.failed == []
        assert result.total_planned == 0
        assert result.total_generated == 0

    def test_partial_success_result(self) -> None:
        """Should track both successes and failures."""
        result = BatchGeneratorResult(
            documents=[],  # Would have Document objects
            failed=["Architecture Doc"],
            total_planned=3,
            total_generated=2,
        )

        assert result.total_planned == 3
        assert result.total_generated == 2
        assert len(result.failed) == 1
        assert "Architecture Doc" in result.failed
