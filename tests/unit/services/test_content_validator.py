"""
Tests for ContentValidator service.

Tests cover:
- Claim extraction from markdown (endpoints, models, technologies)
- Validation against codebase context
- Severity levels for different claim types
- Edge cases: empty content, partial matches
"""

from app.services.docs.content_validator import ContentValidator
from app.services.docs.types import (
    CodebaseContext,
    EndpointInfo,
    ModelInfo,
    TechStack,
)


def _make_tech_stack(
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    databases: list[str] | None = None,
) -> TechStack:
    """Create a TechStack with defaults."""
    return TechStack(
        languages=languages or [],
        frameworks=frameworks or [],
        databases=databases or [],
        infrastructure=[],
        package_managers=[],
    )


def _make_context(
    endpoints: list[EndpointInfo] | None = None,
    models: list[ModelInfo] | None = None,
    tech_stack: TechStack | None = None,
) -> CodebaseContext:
    """Create a CodebaseContext with known entities."""
    return CodebaseContext(
        repositories=[],
        combined_tech_stack=tech_stack or _make_tech_stack(),
        all_key_files=[],
        all_models=models or [],
        all_endpoints=endpoints or [],
        detected_patterns=[],
        total_files=10,
        total_tokens=1000,
        errors=[],
    )


class TestClaimExtraction:
    """Tests for extracting claims from markdown content."""

    def test_extract_endpoints_from_markdown(self):
        """Extracts API endpoints like GET /api/v1/users."""
        context = _make_context()
        validator = ContentValidator(context)

        content = """
        The API provides several endpoints:
        - `GET /api/v1/users` - List all users
        - `POST /api/v1/products` - Create a product
        - `DELETE /api/v1/products/{id}` - Delete a product
        """

        claims = validator.extract_claims(content)

        assert len(claims.endpoints) >= 3
        assert "/api/v1/users" in claims.endpoints
        assert "/api/v1/products" in claims.endpoints

    def test_extract_models_from_markdown(self):
        """Extracts PascalCase model names."""
        context = _make_context()
        validator = ContentValidator(context)

        content = """
        The data layer uses these models:
        - `UserProfile` model handles user data
        - The `OrderItem` entity tracks purchases
        - `ProductAccess` schema controls permissions
        """

        claims = validator.extract_claims(content)

        assert "UserProfile" in claims.models
        assert "OrderItem" in claims.models

    def test_extract_technologies(self):
        """Extracts known technology names."""
        context = _make_context()
        validator = ContentValidator(context)

        content = """
        The backend uses FastAPI with PostgreSQL for storage
        and Redis for caching. The frontend is built with React
        and Next.js.
        """

        claims = validator.extract_claims(content)

        assert "fastapi" in claims.technologies
        assert "postgresql" in claims.technologies or "postgres" in claims.technologies
        assert "redis" in claims.technologies
        assert "react" in claims.technologies

    def test_extract_no_claims_from_empty_content(self):
        """Empty content yields no claims."""
        context = _make_context()
        validator = ContentValidator(context)

        claims = validator.extract_claims("")

        assert claims.endpoints == []
        assert claims.models == []
        assert claims.technologies == []


class TestValidation:
    """Tests for validating claims against codebase context."""

    def test_valid_claims_no_warnings(self):
        """All claims match codebase — no warnings."""
        context = _make_context(
            endpoints=[
                EndpointInfo(
                    path="/api/v1/users", method="GET",
                    file_path="users.py", handler_name="list_users",
                ),
                EndpointInfo(
                    path="/api/v1/products", method="POST",
                    file_path="products.py", handler_name="create_product",
                ),
            ],
            models=[
                ModelInfo(
                    name="User", file_path="models/user.py",
                    model_type="sqlmodel", fields=["id", "email"],
                ),
                ModelInfo(
                    name="Product", file_path="models/product.py",
                    model_type="sqlmodel", fields=["id", "name"],
                ),
            ],
            tech_stack=_make_tech_stack(
                frameworks=["fastapi"], databases=["postgresql"]
            ),
        )
        validator = ContentValidator(context)

        content = """
        `GET /api/v1/users` returns all users.
        The `User` model stores profile data.
        Built with FastAPI and PostgreSQL.
        """

        result = validator.validate(content)

        assert len(result.warnings) == 0
        assert result.claims_verified > 0

    def test_hallucinated_endpoint_generates_warning(self):
        """Endpoint not in codebase generates high-severity warning."""
        context = _make_context(
            endpoints=[
                EndpointInfo(
                    path="/api/v1/users", method="GET",
                    file_path="users.py", handler_name="list_users",
                ),
            ],
        )
        validator = ContentValidator(context)

        content = "`GET /api/v1/payments` handles billing."

        result = validator.validate(content)

        endpoint_warnings = [w for w in result.warnings if w.claim_type == "endpoint"]
        assert len(endpoint_warnings) >= 1
        assert endpoint_warnings[0].severity == "high"

    def test_hallucinated_model_generates_warning(self):
        """Model not in codebase generates high-severity warning."""
        context = _make_context(
            models=[
                ModelInfo(
                    name="User", file_path="user.py",
                    model_type="sqlmodel", fields=["id"],
                ),
            ],
        )
        validator = ContentValidator(context)

        content = "The `InvoiceRecord` model tracks billing."

        result = validator.validate(content)

        model_warnings = [w for w in result.warnings if w.claim_type == "model"]
        assert len(model_warnings) >= 1
        assert model_warnings[0].severity == "high"

    def test_undetected_technology_generates_medium_warning(self):
        """Technology not in tech stack generates medium-severity warning."""
        context = _make_context(
            tech_stack=_make_tech_stack(frameworks=["fastapi"]),
        )
        validator = ContentValidator(context)

        content = "The system uses Redis for caching."

        result = validator.validate(content)

        tech_warnings = [w for w in result.warnings if w.claim_type == "technology"]
        assert len(tech_warnings) >= 1
        assert tech_warnings[0].severity == "medium"

    def test_empty_content_no_warnings(self):
        """Empty content has no claims to check."""
        context = _make_context()
        validator = ContentValidator(context)

        result = validator.validate("")

        assert result.warnings == []
        assert result.claims_checked == 0

    def test_partial_model_match_no_warning(self):
        """Partial model name match (e.g. 'UserProfile' matching 'User') is accepted."""
        context = _make_context(
            models=[
                ModelInfo(
                    name="User", file_path="user.py",
                    model_type="sqlmodel", fields=["id"],
                ),
            ],
        )
        validator = ContentValidator(context)

        content = "The `UserProfile` schema extends user data."

        result = validator.validate(content)

        model_warnings = [w for w in result.warnings if w.claim_type == "model"]
        assert len(model_warnings) == 0  # Partial match accepted

    def test_endpoint_with_different_params_matches(self):
        """Endpoint with different parameter name still matches."""
        context = _make_context(
            endpoints=[
                EndpointInfo(
                    path="/api/v1/products/{product_id}",
                    method="GET",
                    file_path="products.py",
                    handler_name="get_product",
                ),
            ],
        )
        validator = ContentValidator(context)

        content = "`GET /api/v1/products/{id}` returns a product."

        result = validator.validate(content)

        endpoint_warnings = [w for w in result.warnings if w.claim_type == "endpoint"]
        assert len(endpoint_warnings) == 0  # Flexible param matching
