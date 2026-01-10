"""Constants for GitHub service."""

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

