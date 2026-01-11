"""
CodebaseAnalyzer package for deep codebase analysis.

Part of Documentation Agent v2. Performs thorough analysis of repository
contents to build rich context for the DocumentationPlanner.

Module structure:
- analyzer.py: Main CodebaseAnalyzer class
- constants.py: Token budgets, tier patterns, detection indicators
- tech_stack.py: Technology stack detection
- models.py: Data model extraction
- endpoints.py: API endpoint extraction
- patterns.py: Architecture pattern detection
"""

from app.services.docs.codebase_analyzer.analyzer import CodebaseAnalyzer
from app.services.docs.codebase_analyzer.constants import (
    CHARS_PER_TOKEN,
    DATABASE_INDICATORS,
    DEFAULT_TOKEN_BUDGET,
    FRAMEWORK_INDICATORS,
    INFRASTRUCTURE_INDICATORS,
    MAX_FILE_SIZE,
    MODEL_PATTERNS,
    SKIP_PATTERNS,
    TIER_1_PATTERNS,
    TIER_2_PATTERNS,
    TIER_3_PATTERNS,
)
from app.services.docs.codebase_analyzer.endpoints import extract_endpoints
from app.services.docs.codebase_analyzer.models import extract_models
from app.services.docs.codebase_analyzer.patterns import detect_patterns
from app.services.docs.codebase_analyzer.tech_stack import detect_tech_stack

__all__ = [
    # Main class
    "CodebaseAnalyzer",
    # Extraction functions
    "detect_tech_stack",
    "extract_models",
    "extract_endpoints",
    "detect_patterns",
    # Constants
    "CHARS_PER_TOKEN",
    "DEFAULT_TOKEN_BUDGET",
    "MAX_FILE_SIZE",
    "TIER_1_PATTERNS",
    "TIER_2_PATTERNS",
    "TIER_3_PATTERNS",
    "SKIP_PATTERNS",
    "FRAMEWORK_INDICATORS",
    "DATABASE_INDICATORS",
    "INFRASTRUCTURE_INDICATORS",
    "MODEL_PATTERNS",
]
