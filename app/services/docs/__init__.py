"""
Documentation Agent services package.

Provides agents for generating and maintaining documentation:
- DocumentOrchestrator: Coordinates the entire documentation process
- ChangelogAgent: Creates and maintains changelog.md
- BlueprintAgent: Generates overview and architecture docs
- PlansAgent: Manages plan lifecycle (plans → executing → completions → archive)
- DocsSyncService: Two-way GitHub synchronization
- CodebaseAnalyzer: Deep codebase analysis for v2 documentation planning
- DocumentationPlanner: Uses Claude Opus 4.5 to create documentation plans
- DocumentGenerator: Executes plans by generating individual documents
"""

from app.services.docs.blueprint_agent import BlueprintAgent
from app.services.docs.changelog_agent import ChangelogAgent
from app.services.docs.codebase_analyzer import CodebaseAnalyzer
from app.services.docs.custom_generator import CustomDocGenerator
from app.services.docs.document_generator import DocumentGenerator
from app.services.docs.documentation_planner import DocumentationPlanner
from app.services.docs.orchestrator import DocumentOrchestrator
from app.services.docs.plans_agent import PlansAgent
from app.services.docs.sync_service import DocsSyncService
from app.services.docs.types import (
    BatchGeneratorResult,
    BlueprintPlan,
    BlueprintResult,
    ChangeEntry,
    ChangelogResult,
    CodebaseContext,
    CustomDocJob,
    CustomDocRequest,
    CustomDocResult,
    DocsInfo,
    DocumentationPlan,
    DocumentSpec,
    DocumentSyncStatus,
    EndpointInfo,
    FileContent,
    GeneratorResult,
    ImportResult,
    ModelInfo,
    OrchestratorResult,
    PlannedDocument,
    PlannerResult,
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
    "CustomDocGenerator",
    "DocumentationPlanner",
    "DocumentGenerator",
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
    # Types - v2 (DocumentationPlanner)
    "DocumentationPlan",
    "PlannedDocument",
    "PlannerResult",
    # Types - v2 (DocumentGenerator)
    "BatchGeneratorResult",
    "GeneratorResult",
    # Types - Custom Doc Generation
    "CustomDocJob",
    "CustomDocRequest",
    "CustomDocResult",
]
