"""
Section configuration for documentation organization.

Defines the section taxonomy used by DocumentationPlanner and DocumentGenerator
to categorize generated documentation. Mirrors the frontend types in
frontend/src/lib/types/document.ts.
"""

from dataclasses import dataclass
from enum import Enum


class DocumentSection(str, Enum):
    """Top-level documentation sections."""

    TECHNICAL = "technical"
    CONCEPTUAL = "conceptual"


class TechnicalSubsection(str, Enum):
    """Technical documentation subsections (for developers/engineers)."""

    INFRASTRUCTURE = "infrastructure"
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    INTEGRATIONS = "integrations"
    CODE_QUALITY = "code-quality"
    SECURITY = "security"
    PERFORMANCE = "performance"


class ConceptualSubsection(str, Enum):
    """Conceptual documentation subsections (for non-technical stakeholders)."""

    OVERVIEW = "overview"
    CONCEPTS = "concepts"
    WORKFLOWS = "workflows"
    GLOSSARY = "glossary"


@dataclass
class SubsectionConfig:
    """Configuration for a document subsection."""

    id: str
    label: str
    section: DocumentSection
    description: str
    example_topics: list[str]


# All subsection configurations
SUBSECTION_CONFIGS: list[SubsectionConfig] = [
    # Technical subsections
    SubsectionConfig(
        id="infrastructure",
        label="Infrastructure/DevOps",
        section=DocumentSection.TECHNICAL,
        description="Deployment, CI/CD, hosting, environment setup",
        example_topics=["deployment", "docker", "ci/cd", "environment variables", "hosting"],
    ),
    SubsectionConfig(
        id="frontend",
        label="Frontend",
        section=DocumentSection.TECHNICAL,
        description="UI architecture, components, state management, styling",
        example_topics=["react", "components", "state", "hooks", "styling", "routing"],
    ),
    SubsectionConfig(
        id="backend",
        label="Backend",
        section=DocumentSection.TECHNICAL,
        description="API design, services, domain logic",
        example_topics=["api", "endpoints", "services", "domain logic", "handlers"],
    ),
    SubsectionConfig(
        id="database",
        label="Database",
        section=DocumentSection.TECHNICAL,
        description="Schema, migrations, queries",
        example_topics=["schema", "migrations", "models", "queries", "relationships"],
    ),
    SubsectionConfig(
        id="integrations",
        label="Integrations/APIs",
        section=DocumentSection.TECHNICAL,
        description="External services, webhooks, third-party APIs",
        example_topics=["webhooks", "oauth", "third-party apis", "external services"],
    ),
    SubsectionConfig(
        id="code-quality",
        label="Code Quality",
        section=DocumentSection.TECHNICAL,
        description="Testing, linting, code standards",
        example_topics=["testing", "linting", "type checking", "code standards", "ci"],
    ),
    SubsectionConfig(
        id="security",
        label="Security",
        section=DocumentSection.TECHNICAL,
        description="Auth flows, permissions, vulnerabilities",
        example_topics=["authentication", "authorization", "rls", "jwt", "permissions"],
    ),
    SubsectionConfig(
        id="performance",
        label="Performance",
        section=DocumentSection.TECHNICAL,
        description="Caching, optimization, monitoring",
        example_topics=["caching", "optimization", "performance", "monitoring", "metrics"],
    ),
    # Conceptual subsections
    SubsectionConfig(
        id="overview",
        label="Product Overview",
        section=DocumentSection.CONCEPTUAL,
        description="Product overview, value proposition, feature summary",
        example_topics=["what it does", "key features", "value proposition", "getting started"],
    ),
    SubsectionConfig(
        id="concepts",
        label="Core Concepts",
        section=DocumentSection.CONCEPTUAL,
        description="Mental models, key abstractions explained simply",
        example_topics=["core concepts", "mental models", "key abstractions", "how it works"],
    ),
    SubsectionConfig(
        id="workflows",
        label="Workflows",
        section=DocumentSection.CONCEPTUAL,
        description="User journeys, business processes",
        example_topics=["user workflows", "business processes", "user journeys", "procedures"],
    ),
    SubsectionConfig(
        id="glossary",
        label="Glossary",
        section=DocumentSection.CONCEPTUAL,
        description="Term definitions",
        example_topics=["terminology", "definitions", "vocabulary", "key terms"],
    ),
]


def get_subsection_config(subsection_id: str) -> SubsectionConfig | None:
    """Get configuration for a subsection by ID."""
    for config in SUBSECTION_CONFIGS:
        if config.id == subsection_id:
            return config
    return None


def get_subsection_prompt() -> str:
    """
    Generate prompt text describing all sections for the DocumentationPlanner.

    This gives Claude context about the section taxonomy so it can assign
    appropriate sections to each planned document.
    """
    lines: list[str] = [
        "## Documentation Sections",
        "",
        "Each document must be assigned to exactly one section and subsection.",
        "",
        "### Technical Documentation",
        "For developers, engineers, and technical stakeholders.",
        "",
    ]

    # Technical subsections
    for config in SUBSECTION_CONFIGS:
        if config.section == DocumentSection.TECHNICAL:
            topics = ", ".join(config.example_topics[:3])
            lines.append(f"- **{config.id}** ({config.label}): {config.description}")
            lines.append(f"  Example topics: {topics}")

    lines.extend(
        [
            "",
            "### Conceptual Documentation",
            "For PMs, product owners, management, and onboarding. Non-technical language.",
            "",
        ]
    )

    # Conceptual subsections
    for config in SUBSECTION_CONFIGS:
        if config.section == DocumentSection.CONCEPTUAL:
            topics = ", ".join(config.example_topics[:3])
            lines.append(f"- **{config.id}** ({config.label}): {config.description}")
            lines.append(f"  Example topics: {topics}")

    return "\n".join(lines)


# Valid section and subsection values (for validation)
VALID_SECTIONS = {s.value for s in DocumentSection}
VALID_TECHNICAL_SUBSECTIONS = {s.value for s in TechnicalSubsection}
VALID_CONCEPTUAL_SUBSECTIONS = {s.value for s in ConceptualSubsection}
VALID_SUBSECTIONS = VALID_TECHNICAL_SUBSECTIONS | VALID_CONCEPTUAL_SUBSECTIONS
