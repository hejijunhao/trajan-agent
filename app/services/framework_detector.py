"""
Framework Detection utility for identifying project frameworks.

Detects frameworks from manifest files (package.json, pyproject.toml, etc.)
to provide context-aware hints for file selection.

Part of Dynamic Architecture Extraction (Phase 4).
"""

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FrameworkInfo:
    """Information about detected frameworks."""

    name: str
    category: str  # "frontend", "backend", "fullstack", "testing", "build"
    file_patterns: list[str] = field(default_factory=list)  # Suggested file patterns
    directory_hints: list[str] = field(default_factory=list)  # Key directories to look in


# Framework definitions with their detection rules and hints
FRAMEWORK_DEFINITIONS: dict[str, dict[str, str | list[str]]] = {
    # JavaScript/TypeScript Frontend
    "next": {
        "category": "fullstack",
        "patterns": ["app/**/page.tsx", "pages/**/*.tsx", "app/**/layout.tsx"],
        "directories": ["app/", "pages/", "components/", "lib/"],
    },
    "react": {
        "category": "frontend",
        "patterns": ["src/**/*.tsx", "src/**/*.jsx", "src/App.tsx"],
        "directories": ["src/", "components/", "hooks/", "contexts/"],
    },
    "vue": {
        "category": "frontend",
        "patterns": ["src/**/*.vue", "src/App.vue"],
        "directories": ["src/", "components/", "views/", "stores/"],
    },
    "svelte": {
        "category": "frontend",
        "patterns": ["src/**/*.svelte", "src/routes/**/*.svelte"],
        "directories": ["src/", "routes/", "lib/"],
    },
    "angular": {
        "category": "frontend",
        "patterns": ["src/app/**/*.component.ts", "src/app/**/*.module.ts"],
        "directories": ["src/app/", "src/environments/"],
    },
    # JavaScript/TypeScript Backend
    "express": {
        "category": "backend",
        "patterns": ["src/routes/**/*.ts", "src/middleware/**/*.ts", "app.ts"],
        "directories": ["src/routes/", "src/middleware/", "src/controllers/"],
    },
    "nestjs": {
        "category": "backend",
        "patterns": ["src/**/*.controller.ts", "src/**/*.module.ts", "src/**/*.service.ts"],
        "directories": ["src/", "src/modules/"],
    },
    "fastify": {
        "category": "backend",
        "patterns": ["src/routes/**/*.ts", "src/plugins/**/*.ts"],
        "directories": ["src/routes/", "src/plugins/"],
    },
    "hono": {
        "category": "backend",
        "patterns": ["src/**/*.ts", "src/routes/**/*.ts"],
        "directories": ["src/", "src/routes/"],
    },
    # Python Frameworks
    "fastapi": {
        "category": "backend",
        "patterns": ["app/api/**/*.py", "app/routers/**/*.py", "app/models/**/*.py"],
        "directories": ["app/", "app/api/", "app/routers/", "app/models/", "app/services/"],
    },
    "django": {
        "category": "backend",
        "patterns": ["**/views.py", "**/models.py", "**/urls.py", "**/admin.py"],
        "directories": ["apps/", "core/", "api/"],
    },
    "flask": {
        "category": "backend",
        "patterns": ["app/**/*.py", "routes/**/*.py", "models/**/*.py"],
        "directories": ["app/", "routes/", "models/", "blueprints/"],
    },
    "starlette": {
        "category": "backend",
        "patterns": ["app/**/*.py", "routes/**/*.py"],
        "directories": ["app/", "routes/"],
    },
    # Go Frameworks
    "gin": {
        "category": "backend",
        "patterns": ["**/*_handler.go", "**/routes.go", "**/router.go"],
        "directories": ["handlers/", "routes/", "controllers/", "internal/"],
    },
    "echo": {
        "category": "backend",
        "patterns": ["**/*_handler.go", "**/routes.go"],
        "directories": ["handlers/", "routes/", "internal/"],
    },
    "fiber": {
        "category": "backend",
        "patterns": ["**/*_handler.go", "**/routes.go"],
        "directories": ["handlers/", "routes/"],
    },
    # Rust Frameworks
    "actix-web": {
        "category": "backend",
        "patterns": ["src/**/*.rs", "src/routes/**/*.rs"],
        "directories": ["src/", "src/routes/", "src/handlers/"],
    },
    "axum": {
        "category": "backend",
        "patterns": ["src/**/*.rs", "src/routes/**/*.rs"],
        "directories": ["src/", "src/routes/", "src/handlers/"],
    },
    "rocket": {
        "category": "backend",
        "patterns": ["src/**/*.rs"],
        "directories": ["src/"],
    },
    # Java/Kotlin
    "spring": {
        "category": "backend",
        "patterns": [
            "src/main/java/**/*Controller.java",
            "src/main/java/**/*Service.java",
            "src/main/java/**/*Repository.java",
        ],
        "directories": [
            "src/main/java/",
            "src/main/kotlin/",
            "src/main/resources/",
        ],
    },
}


# Dependency to framework name mapping for package.json
JS_DEPENDENCY_FRAMEWORKS: dict[str, str] = {
    "next": "next",
    "react": "react",
    "vue": "vue",
    "svelte": "svelte",
    "@angular/core": "angular",
    "express": "express",
    "@nestjs/core": "nestjs",
    "fastify": "fastify",
    "hono": "hono",
    "koa": "koa",
}

# Dependency to framework name mapping for Python (pyproject.toml / requirements.txt)
PYTHON_DEPENDENCY_FRAMEWORKS: dict[str, str] = {
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "starlette": "starlette",
    "tornado": "tornado",
    "pyramid": "pyramid",
    "aiohttp": "aiohttp",
}


@dataclass
class DetectionResult:
    """Result of framework detection."""

    frameworks: list[FrameworkInfo]
    primary_language: str | None = None
    suggested_patterns: list[str] = field(default_factory=list)
    suggested_directories: list[str] = field(default_factory=list)


class FrameworkDetector:
    """
    Detect frameworks from project manifest files.

    Analyzes package.json, pyproject.toml, go.mod, Cargo.toml, etc.
    to identify frameworks and provide file selection hints.
    """

    def detect(self, files: dict[str, str]) -> DetectionResult:
        """
        Detect frameworks from manifest file contents.

        Args:
            files: Dict mapping file paths to their contents

        Returns:
            DetectionResult with detected frameworks and hints
        """
        frameworks: list[FrameworkInfo] = []
        primary_language: str | None = None

        # Check package.json for JS/TS frameworks
        package_json = files.get("package.json")
        if package_json:
            primary_language = primary_language or "typescript"
            js_frameworks = self._detect_from_package_json(package_json)
            frameworks.extend(js_frameworks)

        # Check pyproject.toml for Python frameworks
        pyproject = files.get("pyproject.toml")
        if pyproject:
            primary_language = primary_language or "python"
            py_frameworks = self._detect_from_pyproject(pyproject)
            frameworks.extend(py_frameworks)

        # Check requirements.txt as fallback for Python
        requirements = files.get("requirements.txt")
        if requirements and not pyproject:
            primary_language = primary_language or "python"
            py_frameworks = self._detect_from_requirements(requirements)
            frameworks.extend(py_frameworks)

        # Check go.mod for Go frameworks
        go_mod = files.get("go.mod")
        if go_mod:
            primary_language = primary_language or "go"
            go_frameworks = self._detect_from_go_mod(go_mod)
            frameworks.extend(go_frameworks)

        # Check Cargo.toml for Rust frameworks
        cargo_toml = files.get("Cargo.toml")
        if cargo_toml:
            primary_language = primary_language or "rust"
            rust_frameworks = self._detect_from_cargo(cargo_toml)
            frameworks.extend(rust_frameworks)

        # Check pom.xml or build.gradle for Java/Kotlin
        pom_xml = files.get("pom.xml")
        build_gradle = files.get("build.gradle") or files.get("build.gradle.kts")
        if pom_xml or build_gradle:
            primary_language = primary_language or "java"
            jvm_frameworks = self._detect_from_jvm(pom_xml, build_gradle)
            frameworks.extend(jvm_frameworks)

        # Aggregate suggested patterns and directories
        suggested_patterns: list[str] = []
        suggested_directories: list[str] = []

        for fw in frameworks:
            suggested_patterns.extend(fw.file_patterns)
            suggested_directories.extend(fw.directory_hints)

        # Deduplicate while preserving order
        suggested_patterns = list(dict.fromkeys(suggested_patterns))
        suggested_directories = list(dict.fromkeys(suggested_directories))

        return DetectionResult(
            frameworks=frameworks,
            primary_language=primary_language,
            suggested_patterns=suggested_patterns,
            suggested_directories=suggested_directories,
        )

    def _detect_from_package_json(self, content: str) -> list[FrameworkInfo]:
        """Detect JS/TS frameworks from package.json."""
        frameworks: list[FrameworkInfo] = []

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse package.json")
            return frameworks

        # Combine dependencies and devDependencies
        deps: dict[str, str] = {}
        deps.update(data.get("dependencies", {}))
        deps.update(data.get("devDependencies", {}))

        # Check for known frameworks
        for dep_name, framework_name in JS_DEPENDENCY_FRAMEWORKS.items():
            if dep_name in deps:
                fw_def = FRAMEWORK_DEFINITIONS.get(framework_name, {})
                frameworks.append(
                    FrameworkInfo(
                        name=framework_name,
                        category=str(fw_def.get("category", "unknown")),
                        file_patterns=list(fw_def.get("patterns", [])),
                        directory_hints=list(fw_def.get("directories", [])),
                    )
                )

        return frameworks

    def _detect_from_pyproject(self, content: str) -> list[FrameworkInfo]:
        """Detect Python frameworks from pyproject.toml."""
        frameworks: list[FrameworkInfo] = []

        # Simple TOML parsing for dependencies (avoid external dependency)
        # Look for dependencies in [project.dependencies] or [tool.poetry.dependencies]
        deps_text = content.lower()

        for dep_name, framework_name in PYTHON_DEPENDENCY_FRAMEWORKS.items():
            # Match patterns:
            # - fastapi = "..." (poetry style)
            # - "fastapi>=..." (PEP 621 list style)
            # - "fastapi" (PEP 621 list style, plain)
            # - fastapi[...] (with extras)
            patterns = [
                rf'["\']?{re.escape(dep_name)}["\']?\s*[=\[>]',  # poetry: fastapi = "..."
                rf'["\']{re.escape(dep_name)}["\']',  # PEP 621: "fastapi" in list
                rf'["\']{re.escape(dep_name)}[>=<\[]',  # PEP 621: "fastapi>=" in list
            ]
            if any(re.search(p, deps_text) for p in patterns):
                fw_def = FRAMEWORK_DEFINITIONS.get(framework_name, {})
                frameworks.append(
                    FrameworkInfo(
                        name=framework_name,
                        category=str(fw_def.get("category", "unknown")),
                        file_patterns=list(fw_def.get("patterns", [])),
                        directory_hints=list(fw_def.get("directories", [])),
                    )
                )

        return frameworks

    def _detect_from_requirements(self, content: str) -> list[FrameworkInfo]:
        """Detect Python frameworks from requirements.txt."""
        frameworks: list[FrameworkInfo] = []
        lines = content.lower().split("\n")

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Extract package name (before ==, >=, etc.)
            match = re.match(r"([a-z0-9_-]+)", line)
            if match:
                pkg_name = match.group(1)
                if pkg_name in PYTHON_DEPENDENCY_FRAMEWORKS:
                    framework_name = PYTHON_DEPENDENCY_FRAMEWORKS[pkg_name]
                    fw_def = FRAMEWORK_DEFINITIONS.get(framework_name, {})
                    frameworks.append(
                        FrameworkInfo(
                            name=framework_name,
                            category=str(fw_def.get("category", "unknown")),
                            file_patterns=list(fw_def.get("patterns", [])),
                            directory_hints=list(fw_def.get("directories", [])),
                        )
                    )

        return frameworks

    def _detect_from_go_mod(self, content: str) -> list[FrameworkInfo]:
        """Detect Go frameworks from go.mod."""
        frameworks: list[FrameworkInfo] = []

        go_frameworks = {
            "github.com/gin-gonic/gin": "gin",
            "github.com/labstack/echo": "echo",
            "github.com/gofiber/fiber": "fiber",
        }

        for import_path, framework_name in go_frameworks.items():
            if import_path in content:
                fw_def = FRAMEWORK_DEFINITIONS.get(framework_name, {})
                frameworks.append(
                    FrameworkInfo(
                        name=framework_name,
                        category=str(fw_def.get("category", "unknown")),
                        file_patterns=list(fw_def.get("patterns", [])),
                        directory_hints=list(fw_def.get("directories", [])),
                    )
                )

        return frameworks

    def _detect_from_cargo(self, content: str) -> list[FrameworkInfo]:
        """Detect Rust frameworks from Cargo.toml."""
        frameworks: list[FrameworkInfo] = []

        rust_frameworks = {
            "actix-web": "actix-web",
            "axum": "axum",
            "rocket": "rocket",
        }

        content_lower = content.lower()
        for crate_name, framework_name in rust_frameworks.items():
            if crate_name in content_lower:
                fw_def = FRAMEWORK_DEFINITIONS.get(framework_name, {})
                frameworks.append(
                    FrameworkInfo(
                        name=framework_name,
                        category=str(fw_def.get("category", "unknown")),
                        file_patterns=list(fw_def.get("patterns", [])),
                        directory_hints=list(fw_def.get("directories", [])),
                    )
                )

        return frameworks

    def _detect_from_jvm(
        self, pom_xml: str | None, build_gradle: str | None
    ) -> list[FrameworkInfo]:
        """Detect JVM frameworks from pom.xml or build.gradle."""
        frameworks: list[FrameworkInfo] = []

        content = (pom_xml or "") + (build_gradle or "")
        content_lower = content.lower()

        # Check for Spring
        if "spring-boot" in content_lower or "springframework" in content_lower:
            fw_def = FRAMEWORK_DEFINITIONS.get("spring", {})
            frameworks.append(
                FrameworkInfo(
                    name="spring",
                    category=str(fw_def.get("category", "unknown")),
                    file_patterns=list(fw_def.get("patterns", [])),
                    directory_hints=list(fw_def.get("directories", [])),
                )
            )

        return frameworks


def format_framework_hints(result: DetectionResult) -> str:
    """
    Format detection result as a prompt hint for Claude.

    Args:
        result: DetectionResult from FrameworkDetector

    Returns:
        Formatted string for inclusion in prompt
    """
    if not result.frameworks:
        return ""

    lines = ["## Detected Frameworks", ""]

    for fw in result.frameworks:
        lines.append(f"- **{fw.name}** ({fw.category})")

    if result.suggested_directories:
        lines.extend(["", "Key directories for this stack:"])
        for d in result.suggested_directories[:8]:  # Limit to avoid prompt bloat
            lines.append(f"- `{d}`")

    return "\n".join(lines)
