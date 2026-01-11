"""
CodebaseAnalyzer constants and configuration.

Contains token budget settings, file tier patterns, and detection indicators
for frameworks, databases, and infrastructure.
"""

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
