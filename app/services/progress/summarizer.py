"""AI-powered progress summarizer using Claude.

Generates concise narrative summaries of development activity
for the Progress tab's Summary view.
"""

from dataclasses import dataclass

from app.services.interpreter.base import BaseInterpreter


@dataclass
class ProgressData:
    """Input data for progress summary generation.

    Contains aggregated statistics and highlights from the progress API.
    """

    period: str  # e.g., "7d", "30d"
    total_commits: int
    total_contributors: int
    total_additions: int
    total_deletions: int
    focus_areas: list[dict[str, str | int]]  # [{path: str, commits: int}, ...]
    top_contributors: list[dict[str, str | int]]  # [{author: str, commits: int}, ...]
    recent_commits: list[dict[str, str]]  # [{message: str, author: str}, ...]


@dataclass
class ProgressNarrative:
    """Output from progress summary generation."""

    summary: str  # 2-4 sentence narrative


class ProgressSummarizer(BaseInterpreter[ProgressData, ProgressNarrative]):
    """Generates concise narrative summaries of development progress.

    Uses Claude to synthesize commit statistics, focus areas, and contributor
    activity into a PM-friendly 2-4 sentence update.
    """

    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 300

    def get_system_prompt(self) -> str:
        return """You are a concise technical communicator summarizing development activity for product managers and stakeholders.

TASK: Write a 2-4 sentence summary of the development activity. Be specific about what was accomplished.

STYLE:
- Lead with the most impactful changes or achievements
- Mention specific focus areas if activity is concentrated
- Note notable contributor activity only if relevant
- Use active voice and concrete language
- Avoid generic phrases like "various improvements" or "multiple changes"

OUTPUT: Write ONLY the summary text. No labels, no bullet points, no formatting. Just 2-4 natural sentences."""

    def format_input(self, input_data: ProgressData) -> str:
        """Format progress data into a structured prompt."""
        lines = [
            f"Development activity for the past {self._period_to_text(input_data.period)}:",
            "",
            "STATS:",
            f"- {input_data.total_commits} commits by {input_data.total_contributors} contributor(s)",
            f"- {input_data.total_additions:,} lines added, {input_data.total_deletions:,} lines removed",
            "",
        ]

        if input_data.focus_areas:
            lines.append("FOCUS AREAS (by commit count):")
            for area in input_data.focus_areas[:5]:
                lines.append(f"- {area['path']}: {area['commits']} commits")
            lines.append("")

        if input_data.top_contributors:
            lines.append("TOP CONTRIBUTORS:")
            for contrib in input_data.top_contributors[:3]:
                lines.append(f"- {contrib['author']}: {contrib['commits']} commits")
            lines.append("")

        if input_data.recent_commits:
            lines.append("RECENT COMMIT MESSAGES:")
            for commit in input_data.recent_commits[:5]:
                # Truncate long messages
                msg = commit.get("message", "")[:80]
                author = commit.get("author", "Unknown")
                lines.append(f"- \"{msg}\" ({author})")

        return "\n".join(lines)

    def parse_output(self, response_text: str) -> ProgressNarrative:
        """Extract the summary text from the response."""
        # The prompt asks for plain text only, so minimal parsing needed
        summary = response_text.strip()

        # Remove any accidental prefixes the model might add
        prefixes_to_remove = ["Summary:", "SUMMARY:", "Here's the summary:", "Here is the summary:"]
        for prefix in prefixes_to_remove:
            if summary.startswith(prefix):
                summary = summary[len(prefix):].strip()

        return ProgressNarrative(summary=summary)

    def _period_to_text(self, period: str) -> str:
        """Convert period code to human-readable text."""
        period_map = {
            "24h": "24 hours",
            "48h": "48 hours",
            "7d": "7 days",
            "14d": "14 days",
            "30d": "30 days",
            "90d": "90 days",
            "365d": "year",
        }
        return period_map.get(period, period)


# Singleton instance
progress_summarizer = ProgressSummarizer()
