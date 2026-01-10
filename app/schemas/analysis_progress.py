"""Pydantic schema for analysis progress updates.

This schema defines the structure of the `analysis_progress` JSONB column
in the products table. It provides real-time progress feedback to users
while the analysis agent is running.

The progress data is ephemeral - it's only meaningful while analysis_status
is "analyzing". Once analysis completes or fails, this field is cleared.
"""

from typing import Literal

from pydantic import BaseModel, Field


class AnalysisProgress(BaseModel):
    """Progress update during product analysis.

    Represents the current stage and activity of the analysis workflow.
    Frontend polls GET /products/{id} and reads this to show progress UI.
    """

    stage: Literal[
        "fetching_repos",
        "scanning_files",
        "analyzing_code",
        "generating_content",
    ] = Field(description="Current stage of the analysis workflow")

    stage_number: int = Field(ge=1, le=4, description="Current stage (1-4)")
    total_stages: int = Field(default=4, description="Total number of stages")

    # Current activity detail
    current_repo: str | None = Field(
        default=None,
        description="Full name of repo currently being processed, e.g., 'owner/repo'",
    )
    current_file: str | None = Field(
        default=None,
        description="Path of file currently being scanned, e.g., 'src/app/page.tsx'",
    )
    files_scanned: int | None = Field(
        default=None,
        description="Number of files scanned so far in current repo",
    )
    total_files: int | None = Field(
        default=None,
        description="Total number of files to scan in current repo",
    )

    # Optional message for additional context
    message: str | None = Field(
        default=None,
        description="Human-readable status message, e.g., 'Connecting to GitHub...'",
    )
