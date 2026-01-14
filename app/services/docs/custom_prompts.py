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
        sections.extend(
            [
                "---",
                "",
                "## Source Files",
                "",
                "Use these source files as reference for accurate, specific documentation:",
                "",
            ]
        )

        # Filter files if focus_paths are specified
        files_to_include = context.all_key_files
        if request.focus_paths:
            files_to_include = [
                f
                for f in context.all_key_files
                if any(focus in f.path for focus in request.focus_paths)
            ]
            # Fall back to all files if no matches
            if not files_to_include:
                files_to_include = context.all_key_files[:10]  # Limit to avoid token overflow

        for file in files_to_include[:15]:  # Limit files to avoid token overflow
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

    # Final instructions
    sections.extend(
        [
            "---",
            "",
            "## Instructions",
            "",
            "Generate the documentation based on the user's request and the context provided.",
            "Be accurate and only include information you can verify from the source files.",
            "",
            "Use the `save_document` tool to output your documentation.",
            "Also suggest a title for this document using the tool.",
        ]
    )

    return "\n".join(sections)
