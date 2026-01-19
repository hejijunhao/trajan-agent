"""
Assessment prompts for critical codebase evaluation.

These prompts generate honest, detailed assessments of code quality, security,
and performance. They're designed to produce actionable, scored evaluations
rather than generic documentation.
"""

from app.services.docs.custom_prompts import MARKDOWN_STYLE_RULES
from app.services.docs.types import CodebaseContext

# Assessment type to subsection mapping
ASSESSMENT_SUBSECTIONS = {
    "code-quality": "code-quality",
    "security": "security",
    "performance": "performance",
}

# Assessment type to document title mapping
ASSESSMENT_TITLES = {
    "code-quality": "Code Quality Assessment",
    "security": "Security Assessment",
    "performance": "Performance Assessment",
}

# ─────────────────────────────────────────────────────────────
# Assessment Prompt Templates
# ─────────────────────────────────────────────────────────────

ASSESSMENT_PROMPTS: dict[str, str] = {
    "code-quality": """
You are a senior software architect conducting a **critical code review**.
Your job is to provide an **honest, unflinching assessment** of code quality.

## Assessment Framework

Evaluate the codebase across these dimensions:

### 1. Code Organization & Architecture (Score: X/10)

- File/folder structure clarity
- Separation of concerns
- Dependency management
- Module cohesion

### 2. Code Readability & Maintainability (Score: X/10)

- Naming conventions
- Function/method length and complexity
- Comment quality and necessity
- Type safety and documentation

### 3. Error Handling & Resilience (Score: X/10)

- Exception handling patterns
- Edge case coverage
- Graceful degradation
- Logging and observability

### 4. Testing & Quality Assurance (Score: X/10)

- Test coverage (if visible)
- Test quality and meaningfulness
- Testing patterns used

### 5. Technical Debt (Score: X/10)

- Code duplication
- Outdated patterns
- TODO/FIXME accumulation
- Deprecated dependencies

## Output Format

1. **Executive Summary** (2-3 sentences, overall verdict)
2. **Scores Table** (dimension, score, one-line rationale)
3. **Critical Issues** (things that MUST be fixed)
4. **Improvement Opportunities** (nice-to-haves)
5. **Strengths** (what's done well)

**BE HONEST.** Don't sugarcoat issues. A mediocre codebase should get mediocre scores.
If you see anti-patterns, name them. If tests are missing, say so.
""",
    "security": """
You are a security engineer conducting a **security assessment**.
Your job is to identify vulnerabilities, risks, and security best practice violations.

## Assessment Framework

### 1. Authentication & Authorization (Risk: LOW/MEDIUM/HIGH/CRITICAL)

- Auth implementation patterns
- Session management
- Permission checking
- Token handling

### 2. Data Protection (Risk: LOW/MEDIUM/HIGH/CRITICAL)

- Sensitive data handling
- Encryption usage
- Data exposure risks
- PII/PHI considerations

### 3. Input Validation & Injection Prevention (Risk: LOW/MEDIUM/HIGH/CRITICAL)

- SQL injection vectors
- XSS opportunities
- Command injection risks
- Path traversal vulnerabilities

### 4. API Security (Risk: LOW/MEDIUM/HIGH/CRITICAL)

- Rate limiting
- CORS configuration
- API key management
- Error message exposure

### 5. Dependencies & Supply Chain (Risk: LOW/MEDIUM/HIGH/CRITICAL)

- Known vulnerable dependencies
- Dependency age/maintenance
- Lock file presence

## Output Format

1. **Risk Summary** (overall security posture: GOOD / NEEDS WORK / CONCERNING / CRITICAL)
2. **Findings Table** (issue, severity, location, recommendation)
3. **Critical Vulnerabilities** (immediate action required)
4. **Security Debt** (known issues to address)
5. **Positive Security Practices** (what's done right)

**BE THOROUGH.** Security issues can be costly. Flag anything suspicious.
""",
    "performance": """
You are a performance engineer conducting a **performance assessment**.
Your job is to identify bottlenecks, inefficiencies, and optimization opportunities.

## Assessment Framework

### 1. Database & Query Performance (Impact: LOW/MEDIUM/HIGH)

- N+1 query patterns
- Missing indexes (inferred from query patterns)
- Unnecessary data fetching
- Connection pooling

### 2. API & Network Efficiency (Impact: LOW/MEDIUM/HIGH)

- Payload sizes
- Caching opportunities
- Unnecessary round trips
- Compression usage

### 3. Frontend Performance (Impact: LOW/MEDIUM/HIGH)

- Bundle size concerns
- Rendering patterns
- State management efficiency
- Asset optimization

### 4. Backend Processing (Impact: LOW/MEDIUM/HIGH)

- Algorithmic complexity
- Memory usage patterns
- Async/sync patterns
- Resource cleanup

### 5. Scalability Concerns (Impact: LOW/MEDIUM/HIGH)

- Stateful components
- Horizontal scaling blockers
- Resource contention points

## Output Format

1. **Performance Summary** (overall assessment: OPTIMIZED / ACCEPTABLE / NEEDS WORK / PROBLEMATIC)
2. **Bottleneck Table** (issue, impact, location, fix)
3. **Quick Wins** (easy optimizations with high impact)
4. **Long-term Improvements** (architectural changes needed)
5. **Performance Strengths** (efficient patterns observed)

**BE SPECIFIC.** Vague performance advice is useless. Point to exact code patterns.
""",
}


def build_assessment_prompt(
    assessment_type: str,
    context: CodebaseContext,
) -> str:
    """
    Build a complete assessment prompt with codebase context.

    Args:
        assessment_type: One of "code-quality", "security", "performance"
        context: Codebase analysis context from CodebaseAnalyzer

    Returns:
        Complete prompt string for Claude
    """
    if assessment_type not in ASSESSMENT_PROMPTS:
        raise ValueError(f"Unknown assessment type: {assessment_type}")

    sections: list[str] = [
        "# Codebase Assessment Request",
        "",
        ASSESSMENT_PROMPTS[assessment_type],
        "",
        "---",
        "",
        "## Project Context",
        "",
    ]

    # Add tech stack context
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

    # Add source files
    if context.all_key_files:
        # For assessments, we want a broad view - include more files
        files_to_include = context.all_key_files[:20]

        sections.extend(
            [
                "---",
                "",
                "## Source Files for Analysis",
                "",
                "**Analyze the following files to form your assessment:**",
                "",
                "```",
                "\n".join(f.path for f in files_to_include),
                "```",
                "",
                "---",
                "",
            ]
        )

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

    # Add markdown style rules
    sections.extend(
        [
            "---",
            "",
            MARKDOWN_STYLE_RULES,
            "",
        ]
    )

    # Final instructions
    sections.extend(
        [
            "---",
            "",
            "## Output Instructions",
            "",
            "Generate a comprehensive assessment based on the framework above.",
            "Be honest and specific. Include file paths and line references where relevant.",
            "",
            "Use the `save_document` tool to output your assessment.",
            "The title should be: " + ASSESSMENT_TITLES.get(assessment_type, "Assessment"),
        ]
    )

    return "\n".join(sections)
