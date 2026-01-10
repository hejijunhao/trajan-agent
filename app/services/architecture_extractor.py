"""
Architecture Extractor service for extracting structured architecture data.

This service uses Claude Sonnet to extract API endpoints, database models,
services, and frontend pages from code files. It uses a focused prompt
and filters to only architecture-relevant files.

Part of the Analysis Agent refactoring (Phase 3).
"""

import asyncio
import logging
import re
from typing import Any, cast

import anthropic
from anthropic import APIError, RateLimitError

from app.config import settings
from app.schemas.product_overview import (
    ApiEndpoint,
    DatabaseModel,
    FrontendPage,
    OverviewArchitecture,
    ServiceInfo,
)
from app.services.github import RepoContext

logger = logging.getLogger(__name__)

# Model for architecture extraction - Sonnet for accurate code understanding
ARCHITECTURE_MODEL = "claude-sonnet-4-20250514"

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]

# File patterns for architecture-relevant files
# These patterns are matched against file paths in the repository tree
ARCHITECTURE_FILE_PATTERNS: list[re.Pattern[str]] = [
    # API/Route files
    re.compile(r".*/(routes|api|endpoints|controllers|handlers)/.*\.(py|ts|js|go|java|rs)$"),
    re.compile(r".*/app\.(py|ts|js)$"),
    re.compile(r".*/main\.(py|ts|js|go)$"),
    re.compile(r".*/server\.(py|ts|js|go)$"),
    re.compile(r".*/router\.(py|ts|js)$"),
    # Model/Schema files
    re.compile(r".*/(models|entities|schemas|types)/.*\.(py|ts|js|go|java|rs)$"),
    re.compile(r".*/models\.(py|ts|js)$"),
    re.compile(r".*/schema\.(py|ts|js)$"),
    re.compile(r".*/types\.(ts|js)$"),
    # Service/Domain files
    re.compile(r".*/(services|domain|usecases|business)/.*\.(py|ts|js|go|java|rs)$"),
    # Frontend page files (Next.js, Nuxt, SvelteKit, etc.)
    re.compile(r".*/pages/.*\.(tsx|jsx|vue|svelte)$"),
    re.compile(r".*/app/.*page\.(tsx|jsx)$"),  # Next.js App Router
    re.compile(r".*/views/.*\.(tsx|jsx|vue|svelte)$"),
    re.compile(r".*/routes/.*\.(tsx|jsx|svelte)$"),  # SvelteKit, Remix
]

# Files to always include if they exist (entry points, configs with routes)
ALWAYS_INCLUDE_FILES: set[str] = {
    "app/main.py",
    "src/main.py",
    "main.py",
    "app.py",
    "server.py",
    "src/app.ts",
    "src/index.ts",
    "src/server.ts",
    "index.ts",
    "app.ts",
    "server.ts",
}


def _is_architecture_file(path: str) -> bool:
    """Check if a file path matches architecture-relevant patterns."""
    # Check always-include files
    if path in ALWAYS_INCLUDE_FILES:
        return True

    # Normalize path for pattern matching
    normalized = "/" + path.lstrip("/")

    # Check patterns
    return any(pattern.match(normalized) for pattern in ARCHITECTURE_FILE_PATTERNS)


def _filter_architecture_files(files: dict[str, str]) -> dict[str, str]:
    """Filter files to only include architecture-relevant ones."""
    return {path: content for path, content in files.items() if _is_architecture_file(path)}


class ArchitectureExtractor:
    """
    Extract structured architecture data using Claude Sonnet.

    This extractor uses a focused prompt to identify:
    - API endpoints (routes with HTTP methods)
    - Database models/entities
    - Backend services and modules
    - Frontend pages/routes

    Sonnet is used for accurate understanding of complex code patterns
    across different frameworks (FastAPI, Express, Next.js, etc.).
    """

    def __init__(self) -> None:
        """Initialize the architecture extractor with Anthropic client."""
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def extract_architecture(
        self,
        repo_contexts: list[RepoContext],
    ) -> OverviewArchitecture:
        """
        Extract architecture components from repository code.

        Args:
            repo_contexts: List of RepoContext objects with fetched files

        Returns:
            OverviewArchitecture with extracted components
        """
        if not repo_contexts:
            return OverviewArchitecture()

        # Filter to architecture-relevant files only
        architecture_files: dict[str, str] = {}
        for ctx in repo_contexts:
            filtered = _filter_architecture_files(ctx.files)
            # Prefix with repo name for multi-repo clarity
            for path, content in filtered.items():
                key = f"{ctx.full_name}/{path}" if len(repo_contexts) > 1 else path
                architecture_files[key] = content

        if not architecture_files:
            logger.info("No architecture-relevant files found")
            return OverviewArchitecture()

        logger.info(f"Extracting architecture from {len(architecture_files)} files")

        # Build focused prompt
        prompt = self._build_prompt(architecture_files)

        # Build tool schema
        tool_schema = self._build_tool_schema()

        # Call Claude with retry logic
        return await self._call_with_retry(prompt, tool_schema)

    async def _call_with_retry(
        self,
        prompt: str,
        tool_schema: dict[str, Any],
    ) -> OverviewArchitecture:
        """Call Claude API with exponential backoff retry."""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.messages.create(
                    model=ARCHITECTURE_MODEL,
                    max_tokens=8000,
                    tools=cast(Any, [tool_schema]),
                    tool_choice=cast(Any, {"type": "tool", "name": "save_architecture"}),
                    messages=[{"role": "user", "content": prompt}],
                )

                return self._parse_response(response)

            except (RateLimitError, APIError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Architecture extraction error (attempt {attempt + 1}/{MAX_RETRIES}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Architecture extraction failed after {MAX_RETRIES} attempts: {e}"
                    )

        # If we get here, all retries failed
        raise last_error or RuntimeError("Architecture extraction failed after retries")

    def _build_prompt(self, files: dict[str, str]) -> str:
        """Build a focused prompt for architecture extraction."""
        sections = [
            "You are extracting structured architecture information from code files.",
            "",
            "## Files",
            "",
        ]

        # Add file contents
        for path, content in files.items():
            sections.append(f"### {path}")
            sections.append("```")
            # Truncate very long files
            if len(content) > 8000:
                sections.append(content[:8000])
                sections.append(f"\n... (truncated, {len(content)} chars total)")
            else:
                sections.append(content)
            sections.append("```")
            sections.append("")

        # Add instructions
        sections.extend(
            [
                "---",
                "",
                "## Task",
                "",
                "Extract and return using the `save_architecture` tool:",
                "",
                "### 1. API Endpoints",
                "Find all API routes/endpoints. For each:",
                "- `method`: HTTP method (GET, POST, PUT, PATCH, DELETE)",
                "- `path`: The route path (e.g., '/api/v1/users', '/products/{id}')",
                "- `description`: Brief description of what it does",
                "",
                "Look for patterns like:",
                "- FastAPI: `@router.get('/path')`, `@app.post('/path')`",
                "- Express: `router.get('/path')`, `app.post('/path')`",
                "- Next.js API: files in `pages/api/` or `app/api/`",
                "- Go: `r.HandleFunc`, `e.GET`, `router.POST`",
                "",
                "### 2. Database Models",
                "Find all database models/entities. For each:",
                "- `name`: Model/table name (e.g., 'User', 'Product')",
                "- `fields`: List of key field names (3-6 most important fields)",
                "",
                "Look for patterns like:",
                "- SQLModel/SQLAlchemy: `class User(SQLModel)`, `class Product(Base)`",
                "- Prisma: `model User {}`",
                "- TypeORM: `@Entity() class User`",
                "- Mongoose: `new Schema({})`",
                "",
                "### 3. Services",
                "Find backend services/modules. For each:",
                "- `name`: Service name (e.g., 'GitHubService', 'AuthService')",
                "- `description`: Brief description of what it does",
                "",
                "Look for patterns like:",
                "- Classes with 'Service', 'Repository', 'Handler' in name",
                "- Modules exporting business logic functions",
                "",
                "### 4. Frontend Pages",
                "Find frontend pages/routes. For each:",
                "- `path`: Route path (e.g., '/dashboard', '/products/[id]')",
                "- `name`: Page name (e.g., 'Dashboard', 'Product Detail')",
                "- `description`: Brief description of what the page shows",
                "",
                "Look for patterns like:",
                "- Next.js: files in `pages/` or `app/*/page.tsx`",
                "- React Router: `<Route path='/...'>`",
                "- Vue Router: `{ path: '/...' }`",
                "",
                "## Guidelines",
                "",
                "- Be exhaustive but concise",
                "- Only include items you actually find in the code",
                "- Don't make up endpoints, models, or pages that don't exist",
                "- For dynamic routes, use bracket notation: `/users/[id]`, `/products/{productId}`",
                "- Keep descriptions brief (5-15 words)",
            ]
        )

        return "\n".join(sections)

    def _build_tool_schema(self) -> dict[str, Any]:
        """Build the tool schema for architecture extraction."""
        return {
            "name": "save_architecture",
            "description": "Save extracted architecture components",
            "input_schema": {
                "type": "object",
                "required": ["api_endpoints", "database_models", "services", "frontend_pages"],
                "properties": {
                    "api_endpoints": {
                        "type": "array",
                        "description": "List of API endpoints found in the code",
                        "items": {
                            "type": "object",
                            "required": ["method", "path", "description"],
                            "properties": {
                                "method": {
                                    "type": "string",
                                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                                },
                                "path": {"type": "string"},
                                "description": {"type": "string"},
                            },
                        },
                    },
                    "database_models": {
                        "type": "array",
                        "description": "List of database models/entities",
                        "items": {
                            "type": "object",
                            "required": ["name", "fields"],
                            "properties": {
                                "name": {"type": "string"},
                                "fields": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                    "services": {
                        "type": "array",
                        "description": "List of backend services/modules",
                        "items": {
                            "type": "object",
                            "required": ["name", "description"],
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                            },
                        },
                    },
                    "frontend_pages": {
                        "type": "array",
                        "description": "List of frontend pages/routes",
                        "items": {
                            "type": "object",
                            "required": ["path", "name", "description"],
                            "properties": {
                                "path": {"type": "string"},
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }

    def _parse_response(self, response: anthropic.types.Message) -> OverviewArchitecture:
        """Parse Claude's response into OverviewArchitecture schema."""
        # Find the tool use block
        tool_use_block = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "save_architecture":
                tool_use_block = block
                break

        if not tool_use_block:
            logger.warning("Claude did not return a save_architecture tool use")
            return OverviewArchitecture()

        data = cast(dict[str, Any], tool_use_block.input)

        return OverviewArchitecture(
            api_endpoints=[
                ApiEndpoint(
                    method=ep.get("method", "GET"),
                    path=ep.get("path", ""),
                    description=ep.get("description", ""),
                )
                for ep in data.get("api_endpoints", [])
            ],
            database_models=[
                DatabaseModel(
                    name=model.get("name", ""),
                    fields=model.get("fields", []),
                )
                for model in data.get("database_models", [])
            ],
            services=[
                ServiceInfo(
                    name=svc.get("name", ""),
                    description=svc.get("description", ""),
                )
                for svc in data.get("services", [])
            ],
            frontend_pages=[
                FrontendPage(
                    path=page.get("path", ""),
                    name=page.get("name", ""),
                    description=page.get("description", ""),
                )
                for page in data.get("frontend_pages", [])
            ],
        )
