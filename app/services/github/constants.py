"""Constants for GitHub service."""

import re

# Standard GitHub language colors (subset of most common)
# Used for visualization in the frontend language breakdown
GITHUB_LANGUAGE_COLORS: dict[str, str] = {
    "Python": "#3572A5",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Java": "#b07219",
    "C++": "#f34b7d",
    "C": "#555555",
    "C#": "#178600",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Ruby": "#701516",
    "PHP": "#4F5D95",
    "Swift": "#F05138",
    "Kotlin": "#A97BFF",
    "Scala": "#c22d40",
    "Shell": "#89e051",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "SCSS": "#c6538c",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
    "Dockerfile": "#384d54",
    "Makefile": "#427819",
    "SQL": "#e38c00",
    "R": "#198CE7",
    "Jupyter Notebook": "#DA5B0B",
    "Markdown": "#083fa1",
    "YAML": "#cb171e",
    "JSON": "#292929",
    "TOML": "#9c4221",
}

# Key files to fetch for AI analysis
# These provide the most context for understanding a codebase
KEY_FILES: list[str] = [
    # Documentation
    "README.md",
    "README",
    "readme.md",
    "CLAUDE.md",
    "claude.md",
    # Python
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    # JavaScript/TypeScript
    "package.json",
    "tsconfig.json",
    # Rust
    "Cargo.toml",
    # Go
    "go.mod",
    # Java/Kotlin
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    # Configuration
    ".env.example",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    "fly.toml",
    "vercel.json",
    "netlify.toml",
    # CI/CD
    ".github/workflows/ci.yml",
    ".github/workflows/ci.yaml",
    ".github/workflows/main.yml",
    ".github/workflows/main.yaml",
]

# Architecture-relevant file patterns for extracting API endpoints, models, services, and pages
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
ALWAYS_INCLUDE_ARCHITECTURE_FILES: set[str] = {
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

# Maximum number of architecture files to fetch (to avoid excessive API calls)
MAX_ARCHITECTURE_FILES = 50

# Maximum size per architecture file (100KB)
MAX_ARCHITECTURE_FILE_SIZE = 100_000
