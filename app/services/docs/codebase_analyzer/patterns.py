"""
Architecture pattern detection for codebase analysis.

Detects common architectural patterns like monorepo, MVC, microservices,
frontend/backend split, etc.
"""

from app.services.docs.types import TechStack
from app.services.github.types import RepoTree


def detect_patterns(
    tree: RepoTree,
    tech_stack: TechStack,
) -> list[str]:
    """
    Detect architectural patterns in the codebase.

    Args:
        tree: RepoTree with file and directory structure
        tech_stack: Detected TechStack for the codebase

    Returns:
        List of detected pattern names
    """
    patterns: list[str] = []

    # Check for monorepo
    if any(d in tree.directories for d in ["packages", "apps", "libs"]):
        patterns.append("Monorepo")

    # Check for frontend/backend split
    has_frontend = any(d in tree.directories for d in ["frontend", "client", "web", "app"])
    has_backend = any(d in tree.directories for d in ["backend", "server", "api"])
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
