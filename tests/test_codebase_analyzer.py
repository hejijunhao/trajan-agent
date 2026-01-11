"""
Tests for CodebaseAnalyzer service.

Tests cover:
- File tier classification
- Tech stack detection
- Model extraction
- Endpoint extraction
- Pattern detection
"""

from app.services.docs.codebase_analyzer import CodebaseAnalyzer
from app.services.docs.codebase_analyzer.endpoints import extract_endpoints
from app.services.docs.codebase_analyzer.models import extract_models
from app.services.docs.codebase_analyzer.patterns import detect_patterns
from app.services.docs.codebase_analyzer.tech_stack import detect_tech_stack
from app.services.docs.types import FileContent, TechStack
from app.services.github.types import RepoTree, RepoTreeItem


class TestFileTierClassification:
    """Tests for file priority tier classification."""

    def setup_method(self) -> None:
        """Create analyzer instance for testing."""
        # Mock GitHub service not needed for tier tests
        self.analyzer = CodebaseAnalyzer.__new__(CodebaseAnalyzer)

    def test_readme_is_tier_1(self) -> None:
        """README files should be tier 1."""
        assert self.analyzer._get_file_tier("README.md") == 1
        assert self.analyzer._get_file_tier("readme.md") == 1
        assert self.analyzer._get_file_tier("README") == 1

    def test_claude_md_is_tier_1(self) -> None:
        """CLAUDE.md files should be tier 1."""
        assert self.analyzer._get_file_tier("CLAUDE.md") == 1
        assert self.analyzer._get_file_tier("claude.md") == 1

    def test_config_files_are_tier_1(self) -> None:
        """Configuration files should be tier 1."""
        assert self.analyzer._get_file_tier("package.json") == 1
        assert self.analyzer._get_file_tier("pyproject.toml") == 1
        assert self.analyzer._get_file_tier("tsconfig.json") == 1
        assert self.analyzer._get_file_tier("Cargo.toml") == 1
        assert self.analyzer._get_file_tier("go.mod") == 1

    def test_infrastructure_files_are_tier_1(self) -> None:
        """Infrastructure files should be tier 1."""
        assert self.analyzer._get_file_tier("Dockerfile") == 1
        assert self.analyzer._get_file_tier("docker-compose.yml") == 1
        assert self.analyzer._get_file_tier("docker-compose.yaml") == 1
        assert self.analyzer._get_file_tier("fly.toml") == 1

    def test_docs_folder_is_tier_1(self) -> None:
        """Files in docs/ folder should be tier 1."""
        assert self.analyzer._get_file_tier("docs/overview.md") == 1
        assert self.analyzer._get_file_tier("docs/api/endpoints.md") == 1

    def test_model_files_are_tier_2(self) -> None:
        """Model/schema files should be tier 2."""
        assert self.analyzer._get_file_tier("app/models.py") == 2
        assert self.analyzer._get_file_tier("app/model.py") == 2
        assert self.analyzer._get_file_tier("src/schemas.py") == 2
        assert self.analyzer._get_file_tier("lib/types.ts") == 2

    def test_route_files_are_tier_2(self) -> None:
        """Route/API files should be tier 2."""
        assert self.analyzer._get_file_tier("app/routes.py") == 2
        assert self.analyzer._get_file_tier("app/api.py") == 2
        assert self.analyzer._get_file_tier("src/api/users.ts") == 2

    def test_entry_points_are_tier_2(self) -> None:
        """Entry point files should be tier 2."""
        assert self.analyzer._get_file_tier("app.py") == 2
        assert self.analyzer._get_file_tier("main.py") == 2
        assert self.analyzer._get_file_tier("backend/app.py") == 2

    def test_test_files_are_tier_3(self) -> None:
        """Test files should be tier 3."""
        assert self.analyzer._get_file_tier("test_something.py") == 3
        assert self.analyzer._get_file_tier("component.test.ts") == 3
        assert self.analyzer._get_file_tier("component.spec.tsx") == 3

    def test_utility_files_are_tier_3(self) -> None:
        """Utility files should be tier 3."""
        assert self.analyzer._get_file_tier("utils.py") == 3
        assert self.analyzer._get_file_tier("helpers.py") == 3

    def test_unknown_files_return_0(self) -> None:
        """Files not matching any pattern should return 0 (skip)."""
        assert self.analyzer._get_file_tier("random.py") == 0
        assert self.analyzer._get_file_tier("something.ts") == 0

    def test_should_skip_node_modules(self) -> None:
        """node_modules should be skipped."""
        assert self.analyzer._should_skip("node_modules/package/index.js") is True

    def test_should_skip_pycache(self) -> None:
        """__pycache__ should be skipped."""
        assert self.analyzer._should_skip("__pycache__/module.pyc") is True

    def test_should_skip_lock_files(self) -> None:
        """Lock files should be skipped."""
        assert self.analyzer._should_skip("package-lock.json") is True
        assert self.analyzer._should_skip("yarn.lock") is True
        assert self.analyzer._should_skip("pnpm-lock.yaml") is True

    def test_should_skip_minified_files(self) -> None:
        """Minified files should be skipped."""
        assert self.analyzer._should_skip("bundle.min.js") is True
        assert self.analyzer._should_skip("styles.min.css") is True


class TestTechStackDetection:
    """Tests for technology stack detection."""

    def setup_method(self) -> None:
        """Create analyzer instance for testing."""
        self.analyzer = CodebaseAnalyzer.__new__(CodebaseAnalyzer)

    def _make_tree(self, files: list[str]) -> RepoTree:
        """Helper to create a RepoTree."""
        return RepoTree(
            sha="abc123",
            files=files,
            directories=[],
            all_items=[RepoTreeItem(path=f, type="blob", size=100, sha="x") for f in files],
            truncated=False,
        )

    def test_detect_python_language(self) -> None:
        """Should detect Python from .py files."""
        files = [FileContent("app.py", "print('hello')", 100, 1, 25)]
        tree = self._make_tree(["app.py", "utils.py"])

        result = detect_tech_stack(files, tree)

        assert "Python" in result.languages
        assert "pip" in result.package_managers

    def test_detect_typescript_language(self) -> None:
        """Should detect TypeScript from .ts/.tsx files."""
        files = [FileContent("index.ts", "const x = 1", 100, 1, 25)]
        tree = self._make_tree(["index.ts", "component.tsx"])

        result = detect_tech_stack(files, tree)

        assert "TypeScript" in result.languages

    def test_detect_fastapi_framework(self) -> None:
        """Should detect FastAPI from imports."""
        content = """
from fastapi import FastAPI

app = FastAPI()
"""
        files = [FileContent("main.py", content, len(content), 1, 100)]
        tree = self._make_tree(["main.py"])

        result = detect_tech_stack(files, tree)

        assert "FastAPI" in result.frameworks

    def test_detect_nextjs_framework(self) -> None:
        """Should detect Next.js from package.json."""
        content = """
{
  "dependencies": {
    "next": "^14.0.0",
    "react": "^18.0.0"
  }
}
"""
        files = [FileContent("package.json", content, len(content), 1, 100)]
        tree = self._make_tree(["package.json"])

        result = detect_tech_stack(files, tree)

        assert "Next.js" in result.frameworks
        assert "React" in result.frameworks

    def test_detect_postgresql_database(self) -> None:
        """Should detect PostgreSQL from connection strings."""
        content = 'DATABASE_URL="postgresql://user:pass@localhost/db"'
        files = [FileContent(".env.example", content, len(content), 1, 50)]
        tree = self._make_tree([".env.example"])

        result = detect_tech_stack(files, tree)

        assert "PostgreSQL" in result.databases

    def test_detect_docker_infrastructure(self) -> None:
        """Should detect Docker from Dockerfile."""
        files = [FileContent("Dockerfile", "FROM python:3.11", 16, 1, 10)]
        tree = self._make_tree(["Dockerfile"])

        result = detect_tech_stack(files, tree)

        assert "Docker" in result.infrastructure

    def test_detect_npm_package_manager(self) -> None:
        """Should detect npm from package.json."""
        files = [FileContent("package.json", "{}", 2, 1, 1)]
        tree = self._make_tree(["package.json"])

        result = detect_tech_stack(files, tree)

        assert "npm" in result.package_managers


class TestModelExtraction:
    """Tests for data model extraction."""

    def setup_method(self) -> None:
        """Create analyzer instance for testing."""
        self.analyzer = CodebaseAnalyzer.__new__(CodebaseAnalyzer)

    def test_extract_sqlmodel_models(self) -> None:
        """Should extract SQLModel class definitions."""
        content = """
class User(SQLModel, table=True):
    id: int
    name: str
    email: str
"""
        files = [FileContent("models.py", content, len(content), 2, 100)]

        result = extract_models(files)

        assert len(result) == 1
        assert result[0].name == "User"
        assert result[0].model_type == "sqlmodel"
        assert "id" in result[0].fields
        assert "name" in result[0].fields

    def test_extract_pydantic_models(self) -> None:
        """Should extract Pydantic BaseModel classes."""
        content = """
class UserCreate(BaseModel):
    name: str
    email: str
"""
        files = [FileContent("schemas.py", content, len(content), 2, 100)]

        result = extract_models(files)

        assert len(result) == 1
        assert result[0].name == "UserCreate"
        assert result[0].model_type == "pydantic"

    def test_extract_typescript_interfaces(self) -> None:
        """Should extract TypeScript interfaces."""
        content = """
interface User {
  id: number;
  name: string;
}
"""
        files = [FileContent("types.ts", content, len(content), 2, 100)]

        result = extract_models(files)

        assert len(result) == 1
        assert result[0].name == "User"
        assert result[0].model_type == "typescript"

    def test_extract_multiple_models(self) -> None:
        """Should extract multiple models from same file."""
        content = """
class User(SQLModel, table=True):
    id: int

class Post(SQLModel, table=True):
    id: int
    user_id: int
"""
        files = [FileContent("models.py", content, len(content), 2, 100)]

        result = extract_models(files)

        assert len(result) == 2
        model_names = [m.name for m in result]
        assert "User" in model_names
        assert "Post" in model_names


class TestEndpointExtraction:
    """Tests for API endpoint extraction."""

    def setup_method(self) -> None:
        """Create analyzer instance for testing."""
        self.analyzer = CodebaseAnalyzer.__new__(CodebaseAnalyzer)

    def test_extract_fastapi_endpoints(self) -> None:
        """Should extract FastAPI route decorators."""
        content = """
@router.get("/users")
async def get_users():
    pass

@router.post("/users")
async def create_user():
    pass
"""
        files = [FileContent("routes.py", content, len(content), 2, 100)]

        result = extract_endpoints(files)

        assert len(result) == 2
        methods = [e.method for e in result]
        assert "GET" in methods
        assert "POST" in methods
        paths = [e.path for e in result]
        assert "/users" in paths

    def test_extract_handler_names(self) -> None:
        """Should extract handler function names."""
        content = """
@app.get("/health")
def health_check():
    return {"status": "ok"}
"""
        files = [FileContent("main.py", content, len(content), 2, 100)]

        result = extract_endpoints(files)

        assert len(result) == 1
        assert result[0].handler_name == "health_check"


class TestPatternDetection:
    """Tests for architectural pattern detection."""

    def setup_method(self) -> None:
        """Create analyzer instance for testing."""
        self.analyzer = CodebaseAnalyzer.__new__(CodebaseAnalyzer)

    def _make_tree(self, directories: list[str]) -> RepoTree:
        """Helper to create a RepoTree with directories."""
        return RepoTree(
            sha="abc123",
            files=[],
            directories=directories,
            all_items=[RepoTreeItem(path=d, type="tree", size=None, sha="x") for d in directories],
            truncated=False,
        )

    def test_detect_monorepo(self) -> None:
        """Should detect monorepo pattern."""
        tree = self._make_tree(["packages", "apps", "libs"])
        tech_stack = TechStack([], [], [], [], [])

        result = detect_patterns(tree, tech_stack)

        assert "Monorepo" in result

    def test_detect_frontend_backend_split(self) -> None:
        """Should detect frontend/backend split."""
        tree = self._make_tree(["frontend", "backend"])
        tech_stack = TechStack([], [], [], [], [])

        result = detect_patterns(tree, tech_stack)

        assert "Frontend/Backend Split" in result

    def test_detect_rest_api(self) -> None:
        """Should detect REST API pattern."""
        tree = self._make_tree([])
        tech_stack = TechStack([], ["FastAPI"], [], [], [])

        result = detect_patterns(tree, tech_stack)

        assert "REST API" in result

    def test_detect_mvc_architecture(self) -> None:
        """Should detect MVC/layered architecture."""
        tree = self._make_tree(["models", "views", "controllers"])
        tech_stack = TechStack([], [], [], [], [])

        result = detect_patterns(tree, tech_stack)

        assert "MVC/Layered Architecture" in result

    def test_detect_domain_driven_design(self) -> None:
        """Should detect Domain-Driven Design pattern."""
        tree = self._make_tree(["domain", "infrastructure", "application"])
        tech_stack = TechStack([], [], [], [], [])

        result = detect_patterns(tree, tech_stack)

        assert "Domain-Driven Design" in result
