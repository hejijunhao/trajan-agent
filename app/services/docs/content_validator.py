"""
ContentValidator - Post-generation validation for custom documentation.

Extracts claims from generated documentation and validates them against
the actual codebase context to detect potential hallucinations.
"""

import re

from app.services.docs.types import (
    CodebaseContext,
    ExtractedClaims,
    ValidationResult,
    ValidationWarning,
)

# ─────────────────────────────────────────────────────────────
# Known Technologies (for matching against tech stack)
# ─────────────────────────────────────────────────────────────

# Common frameworks/libraries that might be mentioned
KNOWN_FRAMEWORKS = {
    # Python
    "fastapi",
    "django",
    "flask",
    "sqlalchemy",
    "sqlmodel",
    "pydantic",
    "celery",
    "pytest",
    "alembic",
    "uvicorn",
    # JavaScript/TypeScript
    "react",
    "next.js",
    "nextjs",
    "vue",
    "angular",
    "express",
    "nest.js",
    "nestjs",
    "prisma",
    "drizzle",
    "tailwind",
    "tailwindcss",
    # Other
    "spring",
    "rails",
    "laravel",
    "gin",
    "echo",
    "actix",
}

# Common databases
KNOWN_DATABASES = {
    "postgresql",
    "postgres",
    "mysql",
    "mariadb",
    "sqlite",
    "mongodb",
    "redis",
    "elasticsearch",
    "dynamodb",
    "cassandra",
    "supabase",
}

# Common infrastructure/services
KNOWN_INFRASTRUCTURE = {
    "docker",
    "kubernetes",
    "k8s",
    "aws",
    "gcp",
    "azure",
    "vercel",
    "fly.io",
    "heroku",
    "nginx",
    "cloudflare",
    "stripe",
    "twilio",
    "sendgrid",
    "auth0",
    "firebase",
    "sentry",
}

ALL_KNOWN_TECHNOLOGIES = KNOWN_FRAMEWORKS | KNOWN_DATABASES | KNOWN_INFRASTRUCTURE


# ─────────────────────────────────────────────────────────────
# Extraction Patterns
# ─────────────────────────────────────────────────────────────

# API endpoint patterns (e.g., GET /api/users, POST /products/{id})
ENDPOINT_PATTERNS = [
    # HTTP method + path: "GET /api/users"
    r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[\w/{}\-\.]+)",
    # Path with api prefix: "/api/v1/users"
    r"(?:endpoint|route|path)s?\s*[:\s]+[`'\"]?(/api/[\w/{}\-\.]+)",
    # Backtick-quoted paths: `GET /users`
    r"`(GET|POST|PUT|PATCH|DELETE)\s+(/[\w/{}\-\.]+)`",
    # Just API paths in backticks: `/api/v1/products`
    r"`(/api/[\w/{}\-\.]+)`",
]

# Model/class name patterns (PascalCase names that look like models)
# Must be at least 2 parts or end with common suffixes
MODEL_PATTERNS = [
    # Explicit model mentions: "User model", "the Product entity"
    r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\s+(?:model|entity|schema|table|class)",
    r"(?:model|entity|schema|table|class)\s+(?:called\s+)?[`'\"]?([A-Z][a-z]+(?:[A-Z][a-z]+)*)",
    # Common model suffixes: UserModel, ProductSchema, OrderEntity
    r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)*(?:Model|Schema|Entity|Table|Record))\b",
    # Backtick-quoted PascalCase: `UserProfile`, `OrderItem`
    r"`([A-Z][a-z]+(?:[A-Z][a-z]+)+)`",
]

# Words to exclude from model detection (common false positives)
MODEL_EXCLUSIONS = {
    "README",
    "JSON",
    "API",
    "URL",
    "HTTP",
    "HTML",
    "CSS",
    "SQL",
    "REST",
    "OAuth",
    "JWT",
    "UUID",
    "CLI",
    "SDK",
    "TypeScript",
    "JavaScript",
    "Python",
    "FastAPI",
    "NextJS",
    "PostgreSQL",
    "GitHub",
    "GitLab",
}


class ContentValidator:
    """
    Validates generated documentation content against codebase context.

    Extracts claims about endpoints, models, and technologies from the
    generated markdown and cross-references them against what was actually
    detected in the codebase analysis.
    """

    def __init__(self, context: CodebaseContext) -> None:
        """
        Initialize validator with codebase context.

        Args:
            context: The codebase analysis context to validate against
        """
        self.context = context
        self._build_known_sets()

    def _build_known_sets(self) -> None:
        """Build sets of known entities from context for fast lookup."""
        # Known endpoints (normalized to lowercase without method)
        self.known_endpoints: set[str] = set()
        for ep in self.context.all_endpoints:
            # Store the path part, normalized
            path = ep.path.lower().rstrip("/")
            self.known_endpoints.add(path)
            # Also store without version prefix for flexibility
            if "/v1/" in path:
                self.known_endpoints.add(path.replace("/v1/", "/"))
            if "/v2/" in path:
                self.known_endpoints.add(path.replace("/v2/", "/"))

        # Known models (lowercase for case-insensitive matching)
        self.known_models: set[str] = {m.name.lower() for m in self.context.all_models}

        # Known technologies (from tech stack, lowercase)
        tech = self.context.combined_tech_stack
        self.known_technologies: set[str] = set()
        for tech_list in [
            tech.languages,
            tech.frameworks,
            tech.databases,
            tech.infrastructure,
            tech.package_managers,
        ]:
            for t in tech_list:
                self.known_technologies.add(t.lower())

    def validate(self, content: str) -> ValidationResult:
        """
        Validate generated content against codebase context.

        Args:
            content: The generated markdown documentation

        Returns:
            ValidationResult with any warnings about potential hallucinations
        """
        claims = self.extract_claims(content)
        return self._validate_claims(claims)

    def extract_claims(self, content: str) -> ExtractedClaims:
        """
        Extract verifiable claims from generated documentation.

        Args:
            content: The generated markdown content

        Returns:
            ExtractedClaims with endpoints, models, and technologies found
        """
        return ExtractedClaims(
            endpoints=self._extract_endpoints(content),
            models=self._extract_models(content),
            technologies=self._extract_technologies(content),
        )

    def _extract_endpoints(self, content: str) -> list[str]:
        """Extract API endpoint paths from content."""
        endpoints: set[str] = set()

        for pattern in ENDPOINT_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                groups = match.groups()
                # Get the path (last group that starts with /)
                for group in reversed(groups):
                    if group and group.startswith("/"):
                        # Normalize: lowercase, remove trailing slash
                        path = group.lower().rstrip("/")
                        # Skip very short paths or common false positives
                        if len(path) > 3 and path not in {"/api", "/v1", "/v2"}:
                            endpoints.add(path)
                        break

        return sorted(endpoints)

    def _extract_models(self, content: str) -> list[str]:
        """Extract model/entity names from content."""
        models: set[str] = set()

        for pattern in MODEL_PATTERNS:
            for match in re.finditer(pattern, content):
                name = match.group(1)
                # Skip exclusions and very short names
                if name not in MODEL_EXCLUSIONS and len(name) > 3:
                    models.add(name)

        return sorted(models)

    def _extract_technologies(self, content: str) -> list[str]:
        """Extract technology names from content."""
        technologies: set[str] = set()
        content_lower = content.lower()

        for tech in ALL_KNOWN_TECHNOLOGIES:
            # Check for word boundary matches
            pattern = rf"\b{re.escape(tech)}\b"
            if re.search(pattern, content_lower):
                technologies.add(tech)

        return sorted(technologies)

    def _validate_claims(self, claims: ExtractedClaims) -> ValidationResult:
        """
        Validate extracted claims against known codebase entities.

        Args:
            claims: The extracted claims to validate

        Returns:
            ValidationResult with warnings for unverified claims
        """
        warnings: list[ValidationWarning] = []
        claims_checked = 0
        claims_verified = 0

        # Validate endpoints
        for endpoint in claims.endpoints:
            claims_checked += 1
            normalized = endpoint.lower().rstrip("/")

            # Check if endpoint exists (with some flexibility)
            if self._endpoint_exists(normalized):
                claims_verified += 1
            else:
                warnings.append(
                    ValidationWarning(
                        claim_type="endpoint",
                        claim=endpoint,
                        message=f"API endpoint '{endpoint}' not found in analyzed codebase",
                        severity="high",
                    )
                )

        # Validate models
        for model in claims.models:
            claims_checked += 1
            normalized = model.lower()

            # Check if model exists (case-insensitive)
            if normalized in self.known_models:
                claims_verified += 1
            else:
                # Check for partial matches (e.g., "UserProfile" might match "User")
                partial_match = any(
                    normalized.startswith(known) or known.startswith(normalized)
                    for known in self.known_models
                )
                if partial_match:
                    claims_verified += 1  # Allow partial matches
                else:
                    warnings.append(
                        ValidationWarning(
                            claim_type="model",
                            claim=model,
                            message=f"Model '{model}' not found in analyzed codebase",
                            severity="high",
                        )
                    )

        # Validate technologies
        for tech in claims.technologies:
            claims_checked += 1
            normalized = tech.lower()

            if normalized in self.known_technologies:
                claims_verified += 1
            else:
                # Technology warnings are lower severity (might be indirectly used)
                warnings.append(
                    ValidationWarning(
                        claim_type="technology",
                        claim=tech,
                        message=f"Technology '{tech}' not detected in codebase analysis",
                        severity="medium",
                    )
                )

        return ValidationResult(
            warnings=warnings,
            claims_checked=claims_checked,
            claims_verified=claims_verified,
        )

    def _endpoint_exists(self, endpoint: str) -> bool:
        """
        Check if an endpoint exists in the codebase.

        Allows for some flexibility (parameter placeholders, version prefixes).
        """
        # Direct match
        if endpoint in self.known_endpoints:
            return True

        # Check with parameter placeholders replaced
        # e.g., "/api/users/{id}" should match "/api/users/{user_id}"
        normalized = re.sub(r"\{[^}]+\}", "{}", endpoint)
        for known in self.known_endpoints:
            known_normalized = re.sub(r"\{[^}]+\}", "{}", known)
            if normalized == known_normalized:
                return True

        # Check prefix match (for nested routes)
        # e.g., "/api/users" should match if "/api/users/{id}" exists
        for known in self.known_endpoints:
            if known.startswith(endpoint) or endpoint.startswith(known):
                return True

        return False
