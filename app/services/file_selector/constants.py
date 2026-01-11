"""
File selector constants and configuration.

Contains model settings, limits, and pattern definitions used for file selection.
"""

# Model for file selection - Haiku for speed and cost efficiency
FILE_SELECTOR_MODEL = "claude-3-5-haiku-20241022"

# Limits
MAX_FILES_TO_SELECT = 50
MIN_FILES_TO_SELECT = 10
MAX_TREE_FILES = 1000  # Truncate tree if larger than this
MAX_TOKENS = 2000

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]

# Priority directories for tree truncation
# When truncating large trees, prioritize these directories
PRIORITY_DIRECTORIES = [
    "src/",
    "app/",
    "lib/",
    "api/",
    "routes/",
    "pages/",
    "components/",
    "models/",
    "services/",
    "controllers/",
    "handlers/",
    "domain/",
    "core/",
    "pkg/",
    "cmd/",
    "internal/",
]

# Heuristic patterns for fallback file selection
FALLBACK_PATTERNS = [
    # Entry points
    r"^(main|index|app|server)\.(py|ts|js|go|rs|java)$",
    r"^src/(main|index|app)\.(py|ts|js|go|rs)$",
    # Routes / API
    r".*/routes?/.*\.(py|ts|js|go)$",
    r".*/api/.*\.(py|ts|js|go)$",
    r".*/(controllers?|handlers?)/.*\.(py|ts|js|go)$",
    # Models
    r".*/models?/.*\.(py|ts|js|go)$",
    r".*/schemas?/.*\.(py|ts|js)$",
    r".*/entities?/.*\.(py|ts|java)$",
    # Services
    r".*/services?/.*\.(py|ts|js|go)$",
    r".*/domain/.*\.(py|ts|js)$",
    # Frontend pages
    r".*/pages?/.*\.(tsx|jsx|vue|svelte)$",
    r".*/app/.*/page\.(tsx|jsx)$",
    r".*/views?/.*\.(tsx|jsx|vue)$",
    # Config
    r"^(pyproject\.toml|package\.json|Cargo\.toml|go\.mod)$",
]

# Source code file extensions
SOURCE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".scala",
    ".rb",
    ".php",
    ".cs",
    ".swift",
    ".vue",
    ".svelte",
}

# Test file indicators
TEST_INDICATORS = [
    "/test/",
    "/tests/",
    "/__tests__/",
    "/spec/",
    "/specs/",
    "_test.",
    ".test.",
    ".spec.",
    "test_",
]

# Key entry points to prioritize in fallback selection
KEY_ENTRY_POINTS = [
    "main.py",
    "app.py",
    "server.py",
    "index.ts",
    "index.js",
    "main.ts",
    "main.go",
    "main.rs",
    "src/main.py",
    "src/index.ts",
    "src/app.ts",
    "app/main.py",
]
