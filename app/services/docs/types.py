"""
Shared data types for Documentation Agent services.

These dataclasses are used across DocumentOrchestrator and sub-agents
(ChangelogAgent, BlueprintAgent, PlansAgent).
"""

from dataclasses import dataclass, field

from app.models.document import Document
from app.services.github.types import RepoTreeItem


@dataclass
class DocsInfo:
    """Information about existing documentation in a repository."""

    has_docs_folder: bool
    has_markdown_files: bool
    files: list[RepoTreeItem]


@dataclass
class ChangelogResult:
    """Result of ChangelogAgent processing."""

    action: str  # "found_existing", "created", "updated"
    document: Document


@dataclass
class ChangeEntry:
    """A single entry for changelog updates."""

    category: str  # "Added", "Changed", "Fixed", "Removed", etc.
    description: str


@dataclass
class DocumentSpec:
    """Specification for a document to be generated."""

    title: str
    folder_path: str
    doc_type: str
    prompt_context: str


@dataclass
class BlueprintPlan:
    """Plan for which blueprint documents need to be created."""

    documents_to_create: list[DocumentSpec] = field(default_factory=list)


@dataclass
class BlueprintResult:
    """Result of BlueprintAgent processing."""

    documents: list[Document] = field(default_factory=list)
    created_count: int = 0


@dataclass
class PlansResult:
    """Result of PlansAgent processing."""

    organized_count: int = 0


@dataclass
class OrchestratorResult:
    """Complete result of DocumentOrchestrator processing."""

    imported: list[Document] = field(default_factory=list)
    changelog: ChangelogResult | None = None
    blueprints: list[Document] = field(default_factory=list)
    plans_structured: PlansResult | None = None
