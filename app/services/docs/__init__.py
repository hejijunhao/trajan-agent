"""
Documentation Agent services package.

Provides agents for generating and maintaining documentation:
- DocumentOrchestrator: Coordinates the entire documentation process
- ChangelogAgent: Creates and maintains changelog.md
- BlueprintAgent: Generates overview and architecture docs
- PlansAgent: Manages plan lifecycle (plans → executing → completions → archive)
- DocsSyncService: Two-way GitHub synchronization
- CodebaseAnalyzer: Deep codebase analysis for v2 documentation planning
"""

from app.services.docs.blueprint_agent import BlueprintAgent
from app.services.docs.changelog_agent import ChangelogAgent
from app.services.docs.codebase_analyzer import CodebaseAnalyzer
from app.services.docs.orchestrator import DocumentOrchestrator
from app.services.docs.plans_agent import PlansAgent
from app.services.docs.sync_service import DocsSyncService
from app.services.docs.types import (
    BlueprintPlan,
    BlueprintResult,
    ChangeEntry,
    ChangelogResult,
    CodebaseContext,
    DocsInfo,
    DocumentSpec,
    DocumentSyncStatus,
    EndpointInfo,
    FileContent,
    ImportResult,
    ModelInfo,
    OrchestratorResult,
    PlansResult,
    RepoAnalysis,
    SyncResult,
    TechStack,
)

__all__ = [
    # Orchestrator
    "DocumentOrchestrator",
    # Agents
    "ChangelogAgent",
    "BlueprintAgent",
    "PlansAgent",
    # Services
    "DocsSyncService",
    "CodebaseAnalyzer",
    # Types - v1
    "BlueprintPlan",
    "BlueprintResult",
    "ChangeEntry",
    "ChangelogResult",
    "DocumentSpec",
    "DocumentSyncStatus",
    "DocsInfo",
    "ImportResult",
    "OrchestratorResult",
    "PlansResult",
    "SyncResult",
    # Types - v2 (CodebaseAnalyzer)
    "CodebaseContext",
    "EndpointInfo",
    "FileContent",
    "ModelInfo",
    "RepoAnalysis",
    "TechStack",
]
