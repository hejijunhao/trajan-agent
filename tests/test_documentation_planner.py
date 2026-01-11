"""
Tests for DocumentationPlanner service.

Tests cover:
- Prompt building with various contexts
- Response parsing from Claude tool use
- Tool schema structure
- Planning result types
- Mode handling (full vs expand)
"""

from unittest.mock import MagicMock

import anthropic

from app.models.document import Document
from app.services.docs.documentation_planner import (
    DOC_TYPES,
    DocumentationPlanner,
)
from app.services.docs.types import (
    CodebaseContext,
    DocumentationPlan,
    EndpointInfo,
    FileContent,
    ModelInfo,
    PlannedDocument,
    PlannerResult,
    RepoAnalysis,
    TechStack,
)


def make_tech_stack(
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    databases: list[str] | None = None,
) -> TechStack:
    """Helper to create a TechStack with defaults."""
    return TechStack(
        languages=languages or [],
        frameworks=frameworks or [],
        databases=databases or [],
        infrastructure=[],
        package_managers=[],
    )


def make_codebase_context(
    repos: list[RepoAnalysis] | None = None,
    tech_stack: TechStack | None = None,
    key_files: list[FileContent] | None = None,
    models: list[ModelInfo] | None = None,
    endpoints: list[EndpointInfo] | None = None,
    patterns: list[str] | None = None,
) -> CodebaseContext:
    """Helper to create a CodebaseContext with defaults."""
    return CodebaseContext(
        repositories=repos or [],
        combined_tech_stack=tech_stack or make_tech_stack(),
        all_key_files=key_files or [],
        all_models=models or [],
        all_endpoints=endpoints or [],
        detected_patterns=patterns or [],
        total_files=10,
        total_tokens=1000,
        errors=[],
    )


def make_repo_analysis(
    full_name: str = "owner/repo",
    description: str | None = None,
    tech_stack: TechStack | None = None,
    patterns: list[str] | None = None,
) -> RepoAnalysis:
    """Helper to create a RepoAnalysis with defaults."""
    return RepoAnalysis(
        full_name=full_name,
        default_branch="main",
        description=description,
        tech_stack=tech_stack or make_tech_stack(),
        key_files=[],
        models=[],
        endpoints=[],
        detected_patterns=patterns or [],
        total_files=10,
        errors=[],
    )


def make_document(
    title: str = "Test Doc",
    doc_type: str = "blueprint",
    folder_path: str = "blueprints",
) -> Document:
    """Helper to create a Document with defaults."""
    doc = Document(
        title=title,
        type=doc_type,
        folder={"path": folder_path},
        content="# Test content",
    )
    return doc


class TestPromptBuilding:
    """Tests for prompt construction."""

    def setup_method(self) -> None:
        """Create planner instance for testing."""
        self.planner = DocumentationPlanner.__new__(DocumentationPlanner)

    def test_prompt_includes_codebase_stats(self) -> None:
        """Prompt should include repository and file counts."""
        context = make_codebase_context()
        context.repositories = [make_repo_analysis()]
        context.total_files = 42
        context.total_tokens = 5000

        prompt = self.planner._build_prompt(context, [], "full")

        assert "Repositories:** 1" in prompt
        assert "Total Files:** 42" in prompt
        assert "5,000" in prompt  # Formatted token count

    def test_prompt_includes_tech_stack(self) -> None:
        """Prompt should include detected technologies."""
        tech = make_tech_stack(
            languages=["Python", "TypeScript"],
            frameworks=["FastAPI", "Next.js"],
            databases=["PostgreSQL"],
        )
        context = make_codebase_context(tech_stack=tech)

        prompt = self.planner._build_prompt(context, [], "full")

        assert "Python" in prompt
        assert "TypeScript" in prompt
        assert "FastAPI" in prompt
        assert "Next.js" in prompt
        assert "PostgreSQL" in prompt

    def test_prompt_includes_detected_patterns(self) -> None:
        """Prompt should include architecture patterns."""
        context = make_codebase_context(patterns=["REST API", "Monorepo"])

        prompt = self.planner._build_prompt(context, [], "full")

        assert "REST API" in prompt
        assert "Monorepo" in prompt

    def test_prompt_includes_models_summary(self) -> None:
        """Prompt should include data model summary."""
        models = [
            ModelInfo("User", "models/user.py", "sqlmodel", ["id", "name"]),
            ModelInfo("Product", "models/product.py", "sqlmodel", ["id", "title"]),
        ]
        context = make_codebase_context(models=models)

        prompt = self.planner._build_prompt(context, [], "full")

        assert "Data Models:** 2" in prompt
        assert "User" in prompt
        assert "Product" in prompt

    def test_prompt_includes_endpoints_summary(self) -> None:
        """Prompt should include API endpoints summary."""
        endpoints = [
            EndpointInfo("GET", "/users", "routes/users.py", "list_users"),
            EndpointInfo("POST", "/users", "routes/users.py", "create_user"),
        ]
        context = make_codebase_context(endpoints=endpoints)

        prompt = self.planner._build_prompt(context, [], "full")

        assert "API Endpoints:** 2" in prompt
        assert "GET /users" in prompt
        assert "POST /users" in prompt

    def test_prompt_includes_key_file_contents(self) -> None:
        """Prompt should include actual file contents."""
        files = [
            FileContent(
                path="README.md",
                content="# My Project\n\nDescription here",
                size=100,
                tier=1,
                token_estimate=25,
            ),
        ]
        context = make_codebase_context(key_files=files)

        prompt = self.planner._build_prompt(context, [], "full")

        assert "README.md" in prompt
        assert "# My Project" in prompt
        assert "Description here" in prompt

    def test_prompt_includes_existing_docs(self) -> None:
        """Prompt should list existing documentation."""
        docs = [
            make_document("Project Overview", "blueprint", "blueprints"),
            make_document("API Reference", "reference", "blueprints"),
        ]
        context = make_codebase_context()

        prompt = self.planner._build_prompt(context, docs, "full")

        assert "Project Overview" in prompt
        assert "API Reference" in prompt
        assert "Do NOT duplicate" in prompt

    def test_prompt_handles_no_existing_docs(self) -> None:
        """Prompt should handle case with no existing docs."""
        context = make_codebase_context()

        prompt = self.planner._build_prompt(context, [], "full")

        assert "No existing documentation found" in prompt

    def test_expand_mode_includes_gap_instructions(self) -> None:
        """Expand mode should emphasize gap analysis."""
        context = make_codebase_context()

        prompt = self.planner._build_prompt(context, [], "expand")

        assert "EXPAND mode" in prompt
        assert "gap" in prompt.lower()
        assert "Do NOT suggest documents that would duplicate" in prompt

    def test_full_mode_no_expand_header(self) -> None:
        """Full mode should not include expand mode instructions."""
        context = make_codebase_context()

        prompt = self.planner._build_prompt(context, [], "full")

        assert "EXPAND mode" not in prompt


class TestToolSchema:
    """Tests for Claude tool schema."""

    def setup_method(self) -> None:
        """Create planner instance for testing."""
        self.planner = DocumentationPlanner.__new__(DocumentationPlanner)

    def test_tool_schema_structure(self) -> None:
        """Tool schema should have correct structure."""
        schema = self.planner._build_tool_schema()

        assert schema["name"] == "save_documentation_plan"
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"

    def test_tool_schema_required_fields(self) -> None:
        """Tool schema should require correct fields."""
        schema = self.planner._build_tool_schema()
        required = schema["input_schema"]["required"]

        assert "summary" in required
        assert "codebase_summary" in required
        assert "planned_documents" in required
        assert "skipped_existing" in required

    def test_tool_schema_doc_type_enum(self) -> None:
        """Tool schema should constrain doc_type to valid values."""
        schema = self.planner._build_tool_schema()
        doc_props = schema["input_schema"]["properties"]["planned_documents"]
        item_props = doc_props["items"]["properties"]

        assert "enum" in item_props["doc_type"]
        assert item_props["doc_type"]["enum"] == DOC_TYPES

    def test_tool_schema_priority_constraints(self) -> None:
        """Tool schema should constrain priority to 1-5."""
        schema = self.planner._build_tool_schema()
        doc_props = schema["input_schema"]["properties"]["planned_documents"]
        priority = doc_props["items"]["properties"]["priority"]

        assert priority["minimum"] == 1
        assert priority["maximum"] == 5


class TestResponseParsing:
    """Tests for parsing Claude responses."""

    def setup_method(self) -> None:
        """Create planner instance for testing."""
        self.planner = DocumentationPlanner.__new__(DocumentationPlanner)

    def _make_tool_use_response(self, input_data: dict) -> anthropic.types.Message:
        """Create a mock Message with tool_use block."""
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "save_documentation_plan"
        tool_use_block.input = input_data

        message = MagicMock(spec=anthropic.types.Message)
        message.content = [tool_use_block]
        return message

    def test_parse_valid_response(self) -> None:
        """Should correctly parse a valid Claude response."""
        input_data = {
            "summary": "This is a FastAPI + Next.js monorepo",
            "codebase_summary": "Full-stack web app with Python backend and React frontend",
            "planned_documents": [
                {
                    "title": "Project Overview",
                    "doc_type": "overview",
                    "purpose": "Introduce new developers to the project",
                    "key_topics": ["Setup", "Architecture", "Contributing"],
                    "source_files": ["README.md", "CLAUDE.md"],
                    "priority": 1,
                    "folder": "blueprints",
                }
            ],
            "skipped_existing": ["API Reference - already exists"],
        }
        response = self._make_tool_use_response(input_data)

        result = self.planner._parse_response(response)

        assert isinstance(result, DocumentationPlan)
        assert result.summary == "This is a FastAPI + Next.js monorepo"
        assert result.codebase_summary == "Full-stack web app with Python backend and React frontend"
        assert len(result.planned_documents) == 1
        assert result.planned_documents[0].title == "Project Overview"
        assert result.planned_documents[0].priority == 1
        assert len(result.skipped_existing) == 1

    def test_parse_multiple_documents(self) -> None:
        """Should correctly parse multiple planned documents."""
        input_data = {
            "summary": "Documentation plan",
            "codebase_summary": "A web app",
            "planned_documents": [
                {
                    "title": "Architecture",
                    "doc_type": "architecture",
                    "purpose": "Technical overview",
                    "key_topics": ["Components", "Data flow"],
                    "source_files": ["backend/app.py"],
                    "priority": 2,
                    "folder": "blueprints",
                },
                {
                    "title": "Getting Started",
                    "doc_type": "guide",
                    "purpose": "Onboarding new developers",
                    "key_topics": ["Installation", "Running locally"],
                    "source_files": ["README.md"],
                    "priority": 1,
                    "folder": "blueprints",
                },
            ],
            "skipped_existing": [],
        }
        response = self._make_tool_use_response(input_data)

        result = self.planner._parse_response(response)

        assert len(result.planned_documents) == 2
        # Should be sorted by priority
        assert result.planned_documents[0].title == "Getting Started"
        assert result.planned_documents[0].priority == 1
        assert result.planned_documents[1].title == "Architecture"
        assert result.planned_documents[1].priority == 2

    def test_parse_handles_missing_optional_fields(self) -> None:
        """Should handle missing optional fields with defaults."""
        input_data = {
            "summary": "Plan",
            "codebase_summary": "App",
            "planned_documents": [
                {
                    "title": "Doc",
                    "doc_type": "overview",
                    "purpose": "Purpose",
                    "key_topics": [],
                    "source_files": [],
                    "priority": 3,
                    "folder": "blueprints",
                }
            ],
            "skipped_existing": [],
        }
        response = self._make_tool_use_response(input_data)

        result = self.planner._parse_response(response)

        assert result.planned_documents[0].key_topics == []
        assert result.planned_documents[0].source_files == []

    def test_parse_fallback_on_invalid_response(self) -> None:
        """Should return empty plan if response is invalid."""
        # Create a response without tool_use
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I cannot create a plan"

        message = MagicMock(spec=anthropic.types.Message)
        message.content = [text_block]

        result = self.planner._parse_response(message)

        assert isinstance(result, DocumentationPlan)
        assert len(result.planned_documents) == 0
        assert "failed" in result.summary.lower()


class TestPlannedDocumentType:
    """Tests for PlannedDocument dataclass."""

    def test_planned_document_creation(self) -> None:
        """Should create PlannedDocument with all fields."""
        doc = PlannedDocument(
            title="API Reference",
            doc_type="reference",
            purpose="Document all API endpoints",
            key_topics=["Authentication", "Endpoints", "Error handling"],
            source_files=["backend/app/api/v1/"],
            priority=2,
            folder="blueprints",
        )

        assert doc.title == "API Reference"
        assert doc.doc_type == "reference"
        assert doc.priority == 2
        assert len(doc.key_topics) == 3

    def test_planned_document_default_folder(self) -> None:
        """Should default to blueprints folder."""
        doc = PlannedDocument(
            title="Overview",
            doc_type="overview",
            purpose="Introduction",
            key_topics=[],
            source_files=[],
            priority=1,
        )

        assert doc.folder == "blueprints"


class TestDocumentationPlanType:
    """Tests for DocumentationPlan dataclass."""

    def test_documentation_plan_creation(self) -> None:
        """Should create DocumentationPlan with all fields."""
        plan = DocumentationPlan(
            summary="Complete documentation suite for this project",
            planned_documents=[
                PlannedDocument(
                    title="Overview",
                    doc_type="overview",
                    purpose="Intro",
                    key_topics=[],
                    source_files=[],
                    priority=1,
                )
            ],
            skipped_existing=["README already covers basics"],
            codebase_summary="FastAPI backend with React frontend",
        )

        assert "Complete documentation" in plan.summary
        assert len(plan.planned_documents) == 1
        assert len(plan.skipped_existing) == 1
        assert "FastAPI" in plan.codebase_summary


class TestPlannerResultType:
    """Tests for PlannerResult dataclass."""

    def test_successful_result(self) -> None:
        """Should create successful PlannerResult."""
        plan = DocumentationPlan(
            summary="Plan",
            planned_documents=[],
            skipped_existing=[],
            codebase_summary="Summary",
        )
        result = PlannerResult(plan=plan, success=True)

        assert result.success is True
        assert result.error is None
        assert result.plan == plan

    def test_failed_result(self) -> None:
        """Should create failed PlannerResult with error."""
        plan = DocumentationPlan(
            summary="Failed",
            planned_documents=[],
            skipped_existing=[],
            codebase_summary="",
        )
        result = PlannerResult(plan=plan, success=False, error="API error occurred")

        assert result.success is False
        assert result.error == "API error occurred"


class TestDocTypeConstants:
    """Tests for document type constants."""

    def test_doc_types_defined(self) -> None:
        """Should have all expected document types."""
        assert "overview" in DOC_TYPES
        assert "architecture" in DOC_TYPES
        assert "guide" in DOC_TYPES
        assert "reference" in DOC_TYPES
        assert "concept" in DOC_TYPES

    def test_doc_types_count(self) -> None:
        """Should have exactly 5 doc types."""
        assert len(DOC_TYPES) == 5
