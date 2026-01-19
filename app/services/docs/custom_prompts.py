"""
Prompt templates for custom document generation.

These templates are combined based on user selections to create the final
prompt for Claude when generating custom documentation.
"""

from app.services.docs.types import CodebaseContext, CustomDocRequest

# ─────────────────────────────────────────────────────────────
# Document Type Instructions
# ─────────────────────────────────────────────────────────────

DOC_TYPE_INSTRUCTIONS: dict[str, str] = {
    "how-to": """Create a step-by-step guide with numbered instructions.
- Start with a brief introduction explaining what the reader will accomplish
- List any prerequisites or requirements upfront
- Provide clear, numbered steps that are easy to follow
- Include code examples or commands where relevant
- Add tips, warnings, or notes for common pitfalls
- End with verification steps to confirm success""",
    "wiki": """Create a comprehensive overview document.
- Provide thorough coverage of the topic
- Organize content with clear sections and subsections
- Include both conceptual explanations and practical details
- Cross-reference related topics where appropriate
- Aim for completeness while remaining accessible""",
    "overview": """Create a high-level summary document.
- Focus on the big picture and key concepts
- Keep explanations concise and accessible
- Highlight the most important aspects
- Avoid deep technical details unless essential
- Help readers quickly understand what something is and why it matters""",
    "technical": """Create detailed technical documentation.
- Provide precise, accurate technical information
- Include implementation details and code examples
- Document parameters, return values, and edge cases
- Use consistent formatting for technical elements
- Assume the reader has technical background""",
    "guide": """Create an instructional guide.
- Structure content for learning, not just reference
- Progress from simple to complex concepts
- Include practical examples throughout
- Anticipate common questions and address them
- Help readers build understanding, not just follow steps""",
}

# ─────────────────────────────────────────────────────────────
# Format Style Instructions
# ─────────────────────────────────────────────────────────────

FORMAT_STYLE_INSTRUCTIONS: dict[str, str] = {
    "technical": """Use precise technical language and structured formatting:
- Use proper markdown headers for organization
- Include code blocks with syntax highlighting
- Use tables for structured data
- Keep prose concise and factual
- Use bullet points for lists of items""",
    "presentation": """Format for visual clarity and quick scanning:
- Use short, punchy bullet points
- Employ headers to create visual hierarchy
- Keep paragraphs very short (1-2 sentences)
- Use bold for emphasis on key terms
- Structure content for slide-like readability""",
    "essay": """Use narrative prose with clear structure:
- Write in flowing paragraphs
- Include an introduction, body, and conclusion
- Use transitions between sections
- Develop ideas fully before moving on
- Balance depth with readability""",
    "email": """Write in professional email format:
- Start with a clear subject/purpose statement
- Keep content concise and scannable
- Use bullet points for action items
- Highlight key information upfront
- End with clear next steps or calls to action""",
    "how-to-guide": """Format as a practical how-to guide:
- Use numbered steps for procedures
- Include "Prerequisites" and "What you'll need" sections
- Add "Tip:", "Warning:", and "Note:" callouts
- Include expected outcomes after key steps
- Add troubleshooting section if relevant""",
}

# ─────────────────────────────────────────────────────────────
# Target Audience Instructions
# ─────────────────────────────────────────────────────────────

AUDIENCE_INSTRUCTIONS: dict[str, str] = {
    "internal-technical": """Writing for internal team members with technical expertise:
- Assume familiarity with the codebase and tech stack
- Use internal terminology and abbreviations freely
- Reference internal systems and conventions
- Focus on implementation details and decisions
- Skip basic explanations of known concepts""",
    "internal-non-technical": """Writing for internal team members without technical background:
- Explain technical concepts in plain language
- Avoid jargon or define it when necessary
- Focus on outcomes and business impact
- Use analogies to explain complex ideas
- Provide context for why technical decisions matter""",
    "external-technical": """Writing for external developers or technical users:
- Provide complete context (don't assume internal knowledge)
- Explain architectural decisions and their rationale
- Use industry-standard terminology
- Include all necessary setup and configuration details
- Be thorough about integration points and requirements""",
    "external-non-technical": """Writing for external users without technical background:
- Use simple, everyday language
- Focus on what things do, not how they work
- Explain benefits and outcomes
- Avoid technical implementation details
- Use concrete examples and real-world analogies""",
}


def build_custom_prompt(request: CustomDocRequest, context: CodebaseContext) -> str:
    """
    Assemble the full prompt from user parameters and codebase context.

    Args:
        request: The user's custom doc request with all parameters
        context: Codebase analysis context from CodebaseAnalyzer

    Returns:
        Complete prompt string for Claude
    """
    sections: list[str] = [
        "You are an expert technical writer creating custom documentation.",
        "",
        "---",
        "",
        "## User Request",
        "",
        f"**What to document:** {request.prompt}",
        "",
    ]

    # Add title if provided
    if request.title:
        sections.append(f"**Requested title:** {request.title}")
        sections.append("")

    # Document type instructions
    sections.extend(
        [
            "---",
            "",
            "## Document Type",
            "",
            DOC_TYPE_INSTRUCTIONS.get(request.doc_type, "Write clear documentation."),
            "",
        ]
    )

    # Format style instructions
    sections.extend(
        [
            "---",
            "",
            "## Format Style",
            "",
            FORMAT_STYLE_INSTRUCTIONS.get(
                request.format_style, "Use standard markdown formatting."
            ),
            "",
        ]
    )

    # Target audience instructions
    sections.extend(
        [
            "---",
            "",
            "## Target Audience",
            "",
            AUDIENCE_INSTRUCTIONS.get(
                request.target_audience,
                "Write for a general technical audience.",
            ),
            "",
        ]
    )

    # Tech stack context
    sections.extend(
        [
            "---",
            "",
            "## Project Context",
            "",
        ]
    )

    tech = context.combined_tech_stack
    if tech.languages:
        sections.append(f"**Languages:** {', '.join(tech.languages)}")
    if tech.frameworks:
        sections.append(f"**Frameworks:** {', '.join(tech.frameworks)}")
    if tech.databases:
        sections.append(f"**Databases:** {', '.join(tech.databases)}")
    if context.detected_patterns:
        sections.append(f"**Architecture:** {', '.join(context.detected_patterns)}")
    sections.append("")

    # Relevant source files (if focus_paths specified, those are prioritized)
    if context.all_key_files:
        # Determine which files to include and track focus status
        files_to_include = context.all_key_files
        focus_note = ""
        fallback_warning = ""

        if request.focus_paths:
            focused_files = [
                f
                for f in context.all_key_files
                if any(focus in f.path for focus in request.focus_paths)
            ]
            if focused_files:
                files_to_include = focused_files
                focus_note = (
                    f"**Focus requested:** {', '.join(request.focus_paths)} "
                    f"({len(focused_files)} matching files found)"
                )
            else:
                # Fallback case - explicitly warn about this
                files_to_include = context.all_key_files[:10]
                focus_note = f"**Focus requested:** {', '.join(request.focus_paths)}"
                fallback_warning = (
                    "**WARNING: No files matched the requested focus paths.** "
                    "Falling back to general codebase files. "
                    "DO NOT document features implied by the focus paths unless you see "
                    "explicit evidence in the files below."
                )

        # Limit files and track truncation
        files_to_include = files_to_include[:15]
        truncated_files = [f for f in files_to_include if len(f.content) > 5000]

        sections.extend(
            [
                "---",
                "",
                "## Source Files",
                "",
            ]
        )

        # Add focus note if applicable
        if focus_note:
            sections.append(focus_note)
            sections.append("")

        # Add fallback warning if applicable
        if fallback_warning:
            sections.append(fallback_warning)
            sections.append("")

        # File transparency: list exactly what's being analyzed
        sections.extend(
            [
                "**You are analyzing ONLY the following files.** If something is not in these "
                "files, it is not visible to you and you should NOT document it as existing:",
                "",
                "```",
                "\n".join(f.path for f in files_to_include),
                "```",
                "",
            ]
        )

        # Truncation warning if applicable
        if truncated_files:
            sections.extend(
                [
                    f"**Note:** {len(truncated_files)} file(s) have been truncated to 5000 "
                    "characters due to size limits. Some implementation details may not be "
                    "visible. State this limitation when relevant rather than guessing at "
                    "hidden content.",
                    "",
                ]
            )

        sections.append("---")
        sections.append("")

        for file in files_to_include:
            sections.extend(
                [
                    f"### `{file.path}`",
                    "",
                    "```",
                    file.content[:5000] if len(file.content) > 5000 else file.content,
                    "```",
                    "",
                ]
            )

    # Final instructions with anti-hallucination rules
    sections.extend(
        [
            "---",
            "",
            "## Critical Documentation Rules",
            "",
            "**IMPORTANT: Follow these rules strictly to ensure accuracy:**",
            "",
            "1. **ONLY document what exists in the provided source files.** Do not invent, "
            "assume, or speculate about features, endpoints, models, or patterns that are "
            "not explicitly visible in the code above.",
            "",
            "2. **If the user asks about something not in the code, say so.** Example: "
            "'The provided source files do not appear to contain a payment processing system.' "
            "Do not generate plausible-sounding documentation about non-existent features.",
            "",
            "3. **Flag uncertainty explicitly.** If you're inferring something rather than "
            "seeing it directly in code, mark it clearly: '[Inferred from file structure]' or "
            "'[Based on naming conventions - not verified in code]'.",
            "",
            "4. **Do not fill gaps with generic content.** If implementation details aren't "
            "visible in the provided files, state: 'Implementation details not visible in "
            "provided files' rather than inventing plausible implementations.",
            "",
            "5. **Avoid these common hallucination patterns:**",
            "   - Inventing API endpoints not defined in the route files shown",
            "   - Describing database tables/models not visible in the schema files",
            "   - Adding features based on project name or description alone",
            "   - Assuming standard patterns (auth, payments, caching) exist without code evidence",
            "   - Describing configuration options not shown in the config files",
            "",
            "---",
            "",
            "## Output Instructions",
            "",
            "Generate the documentation based on the user's request and the source files above.",
            "Be accurate and factual. When in doubt, be conservative rather than speculative.",
            "",
            "Use the `save_document` tool to output your documentation.",
            "Also suggest a title for this document using the tool.",
        ]
    )

    return "\n".join(sections)
