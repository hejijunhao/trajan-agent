"""
Technology stack detection for codebase analysis.

Detects languages, frameworks, databases, infrastructure, and package managers
from file contents and repository structure.
"""

import re

from app.services.docs.codebase_analyzer.constants import (
    DATABASE_INDICATORS,
    FRAMEWORK_INDICATORS,
    INFRASTRUCTURE_INDICATORS,
)
from app.services.docs.types import FileContent, TechStack
from app.services.github.types import RepoTree


def detect_tech_stack(
    files: list[FileContent],
    tree: RepoTree,
) -> TechStack:
    """
    Detect technology stack from file contents and tree structure.

    Args:
        files: List of FileContent objects with file contents
        tree: RepoTree with file and directory structure

    Returns:
        TechStack with detected languages, frameworks, databases, etc.
    """
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
