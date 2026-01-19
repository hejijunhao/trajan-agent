"""
Conceptual document templates for non-technical stakeholders.

These templates provide specialized guidance for generating documentation
that serves PMs, product owners, management, and onboarding — focusing
on clarity, business value, and accessible language.
"""

# Subsection-specific prompts for conceptual documentation
CONCEPTUAL_SUBSECTION_PROMPTS: dict[str, str] = {
    "overview": """Write a product overview for non-technical stakeholders.

Focus on:
- What problem the product solves
- Key features and benefits (not implementation details)
- Who uses it and why they find it valuable
- How it fits into the broader workflow or ecosystem

Style:
- Use simple, everyday language
- Avoid technical jargon entirely
- Explain concepts through analogies and real-world comparisons
- Focus on outcomes and value, not technology""",
    "concepts": """Explain a core concept in simple, accessible terms.

Focus on:
- What this concept IS and why it matters
- Mental models that help understand it
- Real-world analogies to make it concrete
- How this concept relates to things the reader already knows

Style:
- Assume no prior technical knowledge
- Use analogies liberally (e.g., "think of it like...")
- Build from familiar concepts to unfamiliar ones
- Keep explanations short and digestible""",
    "workflows": """Describe a user workflow or business process.

Focus on:
- Clear, numbered steps from start to finish
- Decision points and what to do at each
- Expected outcomes at each stage
- What success looks like

Style:
- Write for someone doing this for the first time
- Use active voice ("Click the button", not "The button should be clicked")
- Include visual cues where helpful (e.g., "Look for the blue Save button")
- Anticipate common questions and address them inline""",
    "glossary": """Define key terms used in this product.

Format:
- Term followed by plain-language definition
- Include context for when/how the term is used
- Group related terms together if helpful

Style:
- Explain technical terms without using other technical terms
- Include examples where they add clarity
- Keep definitions concise (1-3 sentences)
- Cross-reference related terms""",
}


def get_conceptual_prompt(subsection: str) -> str | None:
    """
    Get specialized prompt for a conceptual subsection.

    Args:
        subsection: The conceptual subsection ID (overview, concepts, workflows, glossary)

    Returns:
        Prompt string or None if subsection not found
    """
    return CONCEPTUAL_SUBSECTION_PROMPTS.get(subsection)


def get_conceptual_style_guidance() -> str:
    """
    Get general style guidance for all conceptual documentation.

    This is appended to all conceptual docs regardless of subsection.
    """
    return """
General style for conceptual documentation:
- Write at a high school reading level
- Use short sentences and paragraphs
- Avoid acronyms or define them on first use
- Focus on "what" and "why", not "how it's implemented"
- Use bullet points and headings liberally for scannability
- Include a brief summary or key takeaway at the end
"""
