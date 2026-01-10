"""
Documentation Agent services package.

Provides agents for generating and maintaining documentation:
- DocumentOrchestrator: Coordinates the entire documentation process
- ChangelogAgent: Creates and maintains changelog.md
- BlueprintAgent: Generates overview and architecture docs
- PlansAgent: Manages plan lifecycle (plans → executing → completions → archive)
"""

from app.services.docs.blueprint_agent import BlueprintAgent
from app.services.docs.changelog_agent import ChangelogAgent
from app.services.docs.orchestrator import DocumentOrchestrator
from app.services.docs.plans_agent import PlansAgent
from app.services.docs.types import (
    BlueprintPlan,
    BlueprintResult,
    ChangeEntry,
    ChangelogResult,
    DocsInfo,
    DocumentSpec,
    OrchestratorResult,
    PlansResult,
)

__all__ = [
    # Orchestrator
    "DocumentOrchestrator",
    # Agents
    "ChangelogAgent",
    "BlueprintAgent",
    "PlansAgent",
    # Types
    "BlueprintPlan",
    "BlueprintResult",
    "ChangeEntry",
    "ChangelogResult",
    "DocumentSpec",
    "DocsInfo",
    "OrchestratorResult",
    "PlansResult",
]
