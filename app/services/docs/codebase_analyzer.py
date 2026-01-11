"""
CodebaseAnalyzer - Deep codebase analysis for documentation generation.

Part of Documentation Agent v2. This service performs thorough analysis
of repository contents to build rich context for the DocumentationPlanner.

Key capabilities:
- Smart file selection with priority tiers
- Token budget management
- Framework and pattern detection
- Data model and API endpoint extraction
"""

import logging
import re

from app.models.repository import Repository
from app.services.docs.types import (
    CodebaseContext,
    EndpointInfo,
    FileContent,
    ModelInfo,
    RepoAnalysis,
    TechStack,
)
from app.services.github import GitHubService
from app.services.github.types import RepoTree

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Token Budget Configuration
# ─────────────────────────────────────────────────────────────

# Approximate tokens per character (conservative estimate)
CHARS_PER_TOKEN = 4

# Default token budget for analysis phase (100k tokens ~ 400k chars)
DEFAULT_TOKEN_BUDGET = 100_000

# Maximum file size to fetch (100KB)
MAX_FILE_SIZE = 100_000


# ─────────────────────────────────────────────────────────────
# File Selection Priority Tiers
# ─────────────────────────────────────────────────────────────

# Tier 1: Always include (documentation, config, entry points)
TIER_1_PATTERNS = [
    # Documentation
    r"^README\.md$",
    r"^README$",
    r"^readme\.md$",
    r"^CLAUDE\.md$",
    r"^claude\.md$",
    r"^CONTRIBUTING\.md$",
    r"^docs/.*\.md$",
    # Python config
    r"^pyproject\.toml$",
    r"^setup\.py$",
    r"^requirements\.txt$",
    # JavaScript/TypeScript config
    r"^package\.json$",
    r"^tsconfig\.json$",
    # Rust
    r"^Cargo\.toml$",
    # Go
    r"^go\.mod$",
    # Java/Kotlin
    r"^pom\.xml$",
    r"^build\.gradle(\.kts)?$",
    # Infrastructure
    r"^docker-compose\.ya?ml$",
    r"^Dockerfile$",
    r"^fly\.toml$",
    r"^vercel\.json$",
    r"^\.env\.example$",
]

# Tier 2: Include if budget allows (models, routes, core logic)
TIER_2_PATTERNS = [
    # Python models and routes
    r".*models?\.py$",
    r".*schemas?\.py$",
    r".*routes?\.py$",
    r".*api\.py$",
    r".*endpoints?\.py$",
    r".*views?\.py$",
    # Python entry points
    r"^app\.py$",
    r"^main\.py$",
    r"^server\.py$",
    r".*/app\.py$",
    r".*/main\.py$",
    # TypeScript/JavaScript models and routes
    r".*models?\.tsx?$",
    r".*types?\.tsx?$",
    r".*schemas?\.tsx?$",
    r".*/api/.*\.tsx?$",
    r".*/routes?/.*\.tsx?$",
    # Next.js pages/app router
    r".*pages?/.*\.tsx?$",
    r".*/app/.*page\.tsx?$",
    r".*/app/.*route\.tsx?$",
    # Domain/business logic
    r".*/domain/.*\.py$",
    r".*/services?/.*\.py$",
    r".*/core/.*\.py$",
    # Database
    r".*migrations?/.*\.py$",
    r".*schema\.prisma$",
]

# Tier 3: Summarize only (tests, utilities, generated)
TIER_3_PATTERNS = [
    r".*test.*\.py$",
    r".*\.test\.tsx?$",
    r".*\.spec\.tsx?$",
    r".*__tests__/.*",
    r".*utils?\.py$",
    r".*helpers?\.py$",
    r".*utils?\.tsx?$",
]

# Patterns to always skip
SKIP_PATTERNS = [
    r".*\.min\.js$",
    r".*\.min\.css$",
    r".*\.map$",
    r"node_modules/.*",
    r"\.git/.*",
    r"__pycache__/.*",
    r".*\.pyc$",
    r"dist/.*",
    r"build/.*",
    r"\.next/.*",
    r"coverage/.*",
    r".*\.lock$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
]


# ─────────────────────────────────────────────────────────────
# Framework Detection Patterns
# ─────────────────────────────────────────────────────────────

FRAMEWORK_INDICATORS = {
    # Python frameworks
    "FastAPI": [r"from fastapi", r"import fastapi", r"FastAPI\("],
    "Django": [r"from django", r"import django", r"INSTALLED_APPS"],
    "Flask": [r"from flask", r"import flask", r"Flask\("],
    "SQLAlchemy": [r"from sqlalchemy", r"import sqlalchemy"],
    "SQLModel": [r"from sqlmodel", r"import sqlmodel", r"SQLModel"],
    "Pydantic": [r"from pydantic", r"BaseModel"],
    # JavaScript/TypeScript frameworks
    "Next.js": [r'"next":', r"next/", r"getServerSideProps", r"getStaticProps"],
    "React": [r'"react":', r"from 'react'", r'from "react"', r"useState", r"useEffect"],
    "Express": [r'"express":', r"from 'express'", r"express\(\)"],
    "NestJS": [r'"@nestjs/', r"@Controller", r"@Injectable"],
    "Vue": [r'"vue":', r"createApp", r"defineComponent"],
    "Svelte": [r'"svelte":', r"<script>", r"$:"],
    # Other
    "Prisma": [r"schema\.prisma", r"@prisma/client"],
    "TypeORM": [r'"typeorm":', r"@Entity", r"@Column"],
    "Drizzle": [r'"drizzle-orm":', r"drizzle\("],
}

DATABASE_INDICATORS = {
    "PostgreSQL": [r"postgresql://", r"postgres://", r'"pg":', r"asyncpg"],
    "MySQL": [r"mysql://", r'"mysql":', r"pymysql"],
    "SQLite": [r"sqlite://", r"sqlite3"],
    "MongoDB": [r"mongodb://", r'"mongodb":', r"pymongo"],
    "Redis": [r"redis://", r'"redis":', r'"ioredis":'],
    "Supabase": [r"supabase", r"@supabase/"],
}

INFRASTRUCTURE_INDICATORS = {
    "Docker": [r"Dockerfile", r"docker-compose"],
    "Kubernetes": [r"\.ya?ml$.*kind:\s*(Deployment|Service|Pod)"],
    "Fly.io": [r"fly\.toml"],
    "Vercel": [r"vercel\.json", r'"@vercel/'],
    "AWS": [r"aws-sdk", r"boto3", r"serverless\.ya?ml"],
    "GCP": [r"google-cloud", r"@google-cloud/"],
}

# ─────────────────────────────────────────────────────────────
# API Endpoint Detection Patterns
# ─────────────────────────────────────────────────────────────

# FastAPI/Flask style decorators
PYTHON_ROUTE_PATTERNS = [
    # FastAPI
    r'@(?:app|router)\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>[^"\']+)["\']',
    # Flask
    r'@(?:app|bp|blueprint)\.route\s*\(\s*["\'](?P<path>[^"\']+)["\'].*methods\s*=\s*\[(?P<method>[^\]]+)\]',
]

# Express/Next.js style
JS_ROUTE_PATTERNS = [
    # Express
    r'(?:app|router)\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>[^"\']+)["\']',
    # Next.js API routes (file-based)
    r"export\s+(?:async\s+)?function\s+(?P<method>GET|POST|PUT|DELETE|PATCH)",
]

# ─────────────────────────────────────────────────────────────
# Model Detection Patterns
# ─────────────────────────────────────────────────────────────

MODEL_PATTERNS = {
    # Order matters: more specific patterns first
    "sqlmodel": r"class\s+(\w+)\s*\([^)]*SQLModel[^)]*\)\s*:",
    "pydantic": r"class\s+(\w+)\s*\([^)]*BaseModel[^)]*\)\s*:",
    # SQLAlchemy Base must NOT match BaseModel - require exactly "Base" or "Base,"
    "sqlalchemy": r"class\s+(\w+)\s*\(\s*Base\s*[,)][^)]*\)\s*:",
    "typescript": r"(?:interface|type)\s+(\w+)\s*(?:extends\s+\w+\s*)?\{",
    "prisma": r"model\s+(\w+)\s*\{",
}


class CodebaseAnalyzer:
    """
    Analyzes codebase content to build rich context for documentation.

    Fetches and reads key source files from repositories, identifies
    frameworks, data models, API endpoints, and architectural patterns.
    """

    def __init__(
        self,
        github_service: GitHubService,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> None:
        self.github_service = github_service
        self.token_budget = token_budget

    async def analyze(self, repos: list[Repository]) -> CodebaseContext:
        """
        Perform deep analysis of all repositories.

        Args:
            repos: List of Repository models to analyze

        Returns:
            CodebaseContext with comprehensive analysis results
        """
        all_analyses: list[RepoAnalysis] = []
        all_errors: list[str] = []
        total_tokens = 0

        # Distribute token budget across repos (with minimum per repo)
        per_repo_budget = max(self.token_budget // max(len(repos), 1), 20_000)

        for repo in repos:
            if not repo.full_name:
                all_errors.append(f"Repository {repo.name} has no full_name, skipping")
                continue

            try:
                analysis = await self._analyze_repo(repo, per_repo_budget)
                all_analyses.append(analysis)
                total_tokens += sum(f.token_estimate for f in analysis.key_files)
            except Exception as e:
                error_msg = f"Failed to analyze {repo.full_name}: {e}"
                logger.error(error_msg)
                all_errors.append(error_msg)

        # Combine results across all repos
        return self._combine_analyses(all_analyses, total_tokens, all_errors)

    async def _analyze_repo(
        self,
        repo: Repository,
        token_budget: int,
    ) -> RepoAnalysis:
        """Analyze a single repository."""
        assert repo.full_name is not None
        owner, repo_name = repo.full_name.split("/", 1)
        branch = repo.default_branch or "main"

        errors: list[str] = []

        # Fetch file tree
        try:
            tree = await self.github_service.get_repo_tree(owner, repo_name, branch)
        except Exception as e:
            logger.error(f"Failed to get tree for {repo.full_name}: {e}")
            return RepoAnalysis(
                full_name=repo.full_name,
                default_branch=branch,
                description=repo.description,
                tech_stack=TechStack([], [], [], [], []),
                key_files=[],
                models=[],
                endpoints=[],
                detected_patterns=[],
                total_files=0,
                errors=[str(e)],
            )

        # Select and fetch files with priority tiers
        key_files = await self._fetch_prioritized_files(
            owner, repo_name, branch, tree, token_budget
        )

        # Detect tech stack from file contents
        tech_stack = self._detect_tech_stack(key_files, tree)

        # Extract models and endpoints
        models = self._extract_models(key_files)
        endpoints = self._extract_endpoints(key_files)

        # Detect patterns
        patterns = self._detect_patterns(tree, key_files, tech_stack)

        return RepoAnalysis(
            full_name=repo.full_name,
            default_branch=branch,
            description=repo.description,
            tech_stack=tech_stack,
            key_files=key_files,
            models=models,
            endpoints=endpoints,
            detected_patterns=patterns,
            total_files=len(tree.files),
            errors=errors,
        )

    async def _fetch_prioritized_files(
        self,
        owner: str,
        repo: str,
        branch: str,
        tree: RepoTree,
        token_budget: int,
    ) -> list[FileContent]:
        """
        Fetch files using priority tiers with token budget management.

        Tier 1 files are always fetched, Tier 2 if budget allows,
        Tier 3 only summarized (not content).
        """
        # Classify files by tier
        tier_1_files: list[str] = []
        tier_2_files: list[str] = []
        tier_3_files: list[str] = []

        for file_path in tree.files:
            if self._should_skip(file_path):
                continue

            tier = self._get_file_tier(file_path)
            if tier == 1:
                tier_1_files.append(file_path)
            elif tier == 2:
                tier_2_files.append(file_path)
            elif tier == 3:
                tier_3_files.append(file_path)

        result: list[FileContent] = []
        remaining_budget = token_budget

        # Fetch Tier 1 (always)
        t1_contents = await self.github_service.fetch_files_by_paths(
            owner, repo, tier_1_files, branch, max_size=MAX_FILE_SIZE
        )
        for path, content in t1_contents.items():
            tokens = len(content) // CHARS_PER_TOKEN
            result.append(
                FileContent(
                    path=path,
                    content=content,
                    size=len(content),
                    tier=1,
                    token_estimate=tokens,
                )
            )
            remaining_budget -= tokens

        # Fetch Tier 2 (if budget allows)
        if remaining_budget > 0 and tier_2_files:
            # Limit number of tier 2 files based on remaining budget
            # Estimate ~500 tokens per file average
            max_tier_2 = min(len(tier_2_files), remaining_budget // 500)
            t2_to_fetch = tier_2_files[:max_tier_2]

            t2_contents = await self.github_service.fetch_files_by_paths(
                owner, repo, t2_to_fetch, branch, max_size=MAX_FILE_SIZE
            )
            for path, content in t2_contents.items():
                tokens = len(content) // CHARS_PER_TOKEN
                if tokens <= remaining_budget:
                    result.append(
                        FileContent(
                            path=path,
                            content=content,
                            size=len(content),
                            tier=2,
                            token_estimate=tokens,
                        )
                    )
                    remaining_budget -= tokens

        logger.info(
            f"Fetched {len(result)} files for {owner}/{repo}: "
            f"{len([f for f in result if f.tier == 1])} tier 1, "
            f"{len([f for f in result if f.tier == 2])} tier 2, "
            f"tokens used: {token_budget - remaining_budget}"
        )

        return result

    def _should_skip(self, path: str) -> bool:
        """Check if file should be skipped entirely."""
        return any(re.match(pattern, path, re.IGNORECASE) for pattern in SKIP_PATTERNS)

    def _get_file_tier(self, path: str) -> int:
        """Determine priority tier for a file (1=highest, 3=lowest, 0=skip)."""
        for pattern in TIER_1_PATTERNS:
            if re.match(pattern, path, re.IGNORECASE):
                return 1

        for pattern in TIER_2_PATTERNS:
            if re.match(pattern, path, re.IGNORECASE):
                return 2

        for pattern in TIER_3_PATTERNS:
            if re.match(pattern, path, re.IGNORECASE):
                return 3

        # Default: skip files not matching any pattern
        return 0

    def _detect_tech_stack(
        self,
        files: list[FileContent],
        tree: RepoTree,
    ) -> TechStack:
        """Detect technology stack from file contents and tree structure."""
        # Combine all file contents for pattern matching
        all_content = "\n".join(f.content for f in files)
        all_paths = "\n".join(tree.files)

        languages: set[str] = set()
        frameworks: set[str] = set()
        databases: set[str] = set()
        infrastructure: set[str] = set()
        package_managers: set[str] = set()

        # Detect languages from file extensions
        for path in tree.files:
            if path.endswith(".py"):
                languages.add("Python")
                package_managers.add("pip")
            elif path.endswith(".ts") or path.endswith(".tsx"):
                languages.add("TypeScript")
            elif path.endswith(".js") or path.endswith(".jsx"):
                languages.add("JavaScript")
            elif path.endswith(".rs"):
                languages.add("Rust")
                package_managers.add("cargo")
            elif path.endswith(".go"):
                languages.add("Go")

        # Package managers from config files
        if any(f.path == "package.json" for f in files):
            package_managers.add("npm")
        if any(f.path == "pyproject.toml" for f in files):
            package_managers.add("pip")

        # Detect frameworks
        for framework, patterns in FRAMEWORK_INDICATORS.items():
            for pattern in patterns:
                if re.search(pattern, all_content, re.IGNORECASE):
                    frameworks.add(framework)
                    break

        # Detect databases
        for db, patterns in DATABASE_INDICATORS.items():
            for pattern in patterns:
                if re.search(pattern, all_content, re.IGNORECASE):
                    databases.add(db)
                    break

        # Detect infrastructure
        for infra, patterns in INFRASTRUCTURE_INDICATORS.items():
            for pattern in patterns:
                if re.search(pattern, all_content + all_paths, re.IGNORECASE):
                    infrastructure.add(infra)
                    break

        return TechStack(
            languages=sorted(languages),
            frameworks=sorted(frameworks),
            databases=sorted(databases),
            infrastructure=sorted(infrastructure),
            package_managers=sorted(package_managers),
        )

    def _extract_models(self, files: list[FileContent]) -> list[ModelInfo]:
        """Extract data model definitions from source files."""
        models: list[ModelInfo] = []

        for file in files:
            for model_type, pattern in MODEL_PATTERNS.items():
                matches = re.finditer(pattern, file.content)
                for match in matches:
                    model_name = match.group(1)
                    # Extract field names (simple heuristic)
                    fields = self._extract_fields(file.content, match.end(), model_type)
                    models.append(
                        ModelInfo(
                            name=model_name,
                            file_path=file.path,
                            model_type=model_type,
                            fields=fields[:10],  # Limit to 10 fields
                        )
                    )

        return models

    def _extract_fields(self, content: str, start_pos: int, model_type: str) -> list[str]:
        """Extract field names from a model definition."""
        fields: list[str] = []

        # For TypeScript/Prisma, find braces; for Python, body starts immediately
        if model_type in ("sqlmodel", "pydantic", "sqlalchemy"):
            # Python: body starts at start_pos (after the class declaration colon)
            # Find the end by looking for next class/def at same indentation or EOF
            body_end = start_pos + 500
            next_class = re.search(r"\nclass\s+\w+", content[start_pos:])
            next_def = re.search(r"\ndef\s+\w+", content[start_pos:])
            if next_class:
                body_end = min(body_end, start_pos + next_class.start())
            if next_def:
                body_end = min(body_end, start_pos + next_def.start())
            body = content[start_pos:body_end]
            # Python: field_name: type = ...
            field_matches = re.findall(r"^\s+(\w+)\s*:", body, re.MULTILINE)
            fields = [f for f in field_matches if not f.startswith("_")]
        elif model_type == "typescript":
            # Find opening brace and match to closing
            brace_start = content.find("{", start_pos)
            if brace_start != -1:
                brace_count = 1
                for i in range(brace_start + 1, min(len(content), start_pos + 1000)):
                    if content[i] == "{":
                        brace_count += 1
                    elif content[i] == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            body = content[brace_start + 1 : i]
                            break
                else:
                    body = content[brace_start + 1 : start_pos + 500]
                field_matches = re.findall(r"^\s+(\w+)\s*[?:]", body, re.MULTILINE)
                fields = field_matches
        elif model_type == "prisma":
            # Similar to TypeScript
            brace_start = content.find("{", start_pos)
            if brace_start != -1:
                brace_end = content.find("}", brace_start)
                if brace_end != -1:
                    body = content[brace_start + 1 : brace_end]
                    field_matches = re.findall(r"^\s+(\w+)\s+\w+", body, re.MULTILINE)
                    fields = field_matches

        return fields

    def _extract_endpoints(self, files: list[FileContent]) -> list[EndpointInfo]:
        """Extract API endpoint definitions from source files."""
        endpoints: list[EndpointInfo] = []

        for file in files:
            is_python = file.path.endswith(".py")
            is_js_ts = file.path.endswith((".js", ".jsx", ".ts", ".tsx"))

            # Python routes (only for .py files)
            if is_python:
                for pattern in PYTHON_ROUTE_PATTERNS:
                    matches = re.finditer(pattern, file.content, re.IGNORECASE)
                    for match in matches:
                        method = match.group("method").upper()
                        path = match.group("path")
                        # Try to find the function name
                        handler = self._find_handler_name(file.content, match.end())
                        endpoints.append(
                            EndpointInfo(
                                method=method,
                                path=path,
                                file_path=file.path,
                                handler_name=handler,
                            )
                        )

            # JavaScript/TypeScript routes (only for .js/.ts files)
            if is_js_ts:
                for pattern in JS_ROUTE_PATTERNS:
                    matches = re.finditer(pattern, file.content, re.IGNORECASE)
                    for match in matches:
                        groups = match.groupdict()
                        method = groups.get("method", "GET").upper()
                        path = groups.get("path", "/")
                        endpoints.append(
                            EndpointInfo(
                                method=method,
                                path=path,
                                file_path=file.path,
                            handler_name=None,
                        )
                    )

        return endpoints

    def _find_handler_name(self, content: str, start_pos: int) -> str | None:
        """Find the function name following a route decorator."""
        # Look for async def or def after the decorator
        match = re.search(r"(?:async\s+)?def\s+(\w+)", content[start_pos : start_pos + 200])
        return match.group(1) if match else None

    def _detect_patterns(
        self,
        tree: RepoTree,
        _files: list[FileContent],
        tech_stack: TechStack,
    ) -> list[str]:
        """Detect architectural patterns in the codebase."""
        patterns: list[str] = []

        # Check for monorepo
        if any(d in tree.directories for d in ["packages", "apps", "libs"]):
            patterns.append("Monorepo")

        # Check for frontend/backend split
        has_frontend = any(
            d in tree.directories for d in ["frontend", "client", "web", "app"]
        )
        has_backend = any(
            d in tree.directories for d in ["backend", "server", "api"]
        )
        if has_frontend and has_backend:
            patterns.append("Frontend/Backend Split")

        # API style detection
        if "FastAPI" in tech_stack.frameworks or "Express" in tech_stack.frameworks:
            patterns.append("REST API")

        # Check for microservices
        service_dirs = [d for d in tree.directories if "service" in d.lower()]
        if len(service_dirs) >= 3:
            patterns.append("Microservices")

        # Check for MVC/layered architecture
        has_models = any("models" in d or "model" in d for d in tree.directories)
        has_views = any("views" in d or "templates" in d for d in tree.directories)
        has_controllers = any("controllers" in d or "routes" in d for d in tree.directories)
        if has_models and (has_views or has_controllers):
            patterns.append("MVC/Layered Architecture")

        # Check for domain-driven design
        if any("domain" in d for d in tree.directories):
            patterns.append("Domain-Driven Design")

        return patterns

    def _combine_analyses(
        self,
        analyses: list[RepoAnalysis],
        total_tokens: int,
        errors: list[str],
    ) -> CodebaseContext:
        """Combine analyses from multiple repositories."""
        if not analyses:
            return CodebaseContext(
                repositories=[],
                combined_tech_stack=TechStack([], [], [], [], []),
                all_key_files=[],
                all_models=[],
                all_endpoints=[],
                detected_patterns=[],
                total_files=0,
                total_tokens=0,
                errors=errors,
            )

        # Merge tech stacks
        all_languages: set[str] = set()
        all_frameworks: set[str] = set()
        all_databases: set[str] = set()
        all_infra: set[str] = set()
        all_pkg_managers: set[str] = set()

        all_key_files: list[FileContent] = []
        all_models: list[ModelInfo] = []
        all_endpoints: list[EndpointInfo] = []
        all_patterns: set[str] = set()
        total_files = 0

        for analysis in analyses:
            all_languages.update(analysis.tech_stack.languages)
            all_frameworks.update(analysis.tech_stack.frameworks)
            all_databases.update(analysis.tech_stack.databases)
            all_infra.update(analysis.tech_stack.infrastructure)
            all_pkg_managers.update(analysis.tech_stack.package_managers)

            all_key_files.extend(analysis.key_files)
            all_models.extend(analysis.models)
            all_endpoints.extend(analysis.endpoints)
            all_patterns.update(analysis.detected_patterns)
            total_files += analysis.total_files
            errors.extend(analysis.errors)

        combined_tech_stack = TechStack(
            languages=sorted(all_languages),
            frameworks=sorted(all_frameworks),
            databases=sorted(all_databases),
            infrastructure=sorted(all_infra),
            package_managers=sorted(all_pkg_managers),
        )

        return CodebaseContext(
            repositories=analyses,
            combined_tech_stack=combined_tech_stack,
            all_key_files=all_key_files,
            all_models=all_models,
            all_endpoints=all_endpoints,
            detected_patterns=sorted(all_patterns),
            total_files=total_files,
            total_tokens=total_tokens,
            errors=errors,
        )
