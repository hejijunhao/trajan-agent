"""
Data model extraction for codebase analysis.

Extracts data model definitions (SQLModel, Pydantic, SQLAlchemy, TypeScript, Prisma)
from source files.
"""

import re

from app.services.docs.codebase_analyzer.constants import MODEL_PATTERNS
from app.services.docs.types import FileContent, ModelInfo


def extract_models(files: list[FileContent]) -> list[ModelInfo]:
    """
    Extract data model definitions from source files.

    Args:
        files: List of FileContent objects to search

    Returns:
        List of ModelInfo objects describing found models
    """
    models: list[ModelInfo] = []

    for file in files:
        for model_type, pattern in MODEL_PATTERNS.items():
            matches = re.finditer(pattern, file.content)
            for match in matches:
                model_name = match.group(1)
                # Extract field names (simple heuristic)
                fields = _extract_fields(file.content, match.end(), model_type)
                models.append(
                    ModelInfo(
                        name=model_name,
                        file_path=file.path,
                        model_type=model_type,
                        fields=fields[:10],  # Limit to 10 fields
                    )
                )

    return models


def _extract_fields(content: str, start_pos: int, model_type: str) -> list[str]:
    """
    Extract field names from a model definition.

    Args:
        content: Full file content
        start_pos: Position after the class/model declaration
        model_type: Type of model (sqlmodel, pydantic, typescript, etc.)

    Returns:
        List of field names
    """
    fields: list[str] = []

    # For TypeScript/Prisma, find braces; for Python, body starts immediately
    if model_type in ("sqlmodel", "pydantic", "sqlalchemy"):
        # Python: body starts at start_pos (after the class declaration colon)
        # Find the end by looking for next class/def at same indentation or EOF
        body_end = start_pos + 500
        next_class = re.search(r"\nclass\s+\w+", content[start_pos:])
        next_def = re.search(r"\ndef\s+\w+", content[start_pos:])
        if next_class:
            body_end = min(body_end, start_pos + next_class.start())
        if next_def:
            body_end = min(body_end, start_pos + next_def.start())
        body = content[start_pos:body_end]
        # Python: field_name: type = ...
        field_matches = re.findall(r"^\s+(\w+)\s*:", body, re.MULTILINE)
        fields = [f for f in field_matches if not f.startswith("_")]
    elif model_type == "typescript":
        # Find opening brace and match to closing
        brace_start = content.find("{", start_pos)
        if brace_start != -1:
            brace_count = 1
            for i in range(brace_start + 1, min(len(content), start_pos + 1000)):
                if content[i] == "{":
                    brace_count += 1
                elif content[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        body = content[brace_start + 1 : i]
                        break
            else:
                body = content[brace_start + 1 : start_pos + 500]
            field_matches = re.findall(r"^\s+(\w+)\s*[?:]", body, re.MULTILINE)
            fields = field_matches
    elif model_type == "prisma":
        # Similar to TypeScript
        brace_start = content.find("{", start_pos)
        if brace_start != -1:
            brace_end = content.find("}", brace_start)
            if brace_end != -1:
                body = content[brace_start + 1 : brace_end]
                field_matches = re.findall(r"^\s+(\w+)\s+\w+", body, re.MULTILINE)
                fields = field_matches

    return fields
