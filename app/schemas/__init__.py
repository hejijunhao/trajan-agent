"""Pydantic schemas for API request/response validation."""

from app.schemas.analysis_progress import AnalysisProgress
from app.schemas.docs import (
    AddChangelogEntryRequest,
    ChangeEntryRequest,
    DocsStatusResponse,
    DocumentGrouped,
    DocumentsGroupedResponse,
    GenerateDocsResponse,
)
from app.schemas.product_overview import (
    AnalyzeProductResponse,
    ApiEndpoint,
    ContributorStat,
    DatabaseModel,
    FrontendPage,
    LanguageStat,
    OverviewArchitecture,
    OverviewStats,
    OverviewSummary,
    ProductOverview,
    ServiceInfo,
)

__all__ = [
    "AddChangelogEntryRequest",
    "AnalysisProgress",
    "AnalyzeProductResponse",
    "ApiEndpoint",
    "ChangeEntryRequest",
    "ContributorStat",
    "DatabaseModel",
    "DocumentGrouped",
    "DocumentsGroupedResponse",
    "DocsStatusResponse",
    "FrontendPage",
    "GenerateDocsResponse",
    "LanguageStat",
    "OverviewArchitecture",
    "OverviewStats",
    "OverviewSummary",
    "ProductOverview",
    "ServiceInfo",
]
