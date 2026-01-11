"""
API endpoint extraction for codebase analysis.

Extracts API endpoint definitions from source files for FastAPI, Flask,
Express, and Next.js applications.
"""

import re

from app.services.docs.codebase_analyzer.constants import (
    JS_ROUTE_PATTERNS,
    PYTHON_ROUTE_PATTERNS,
)
from app.services.docs.types import EndpointInfo, FileContent


def extract_endpoints(files: list[FileContent]) -> list[EndpointInfo]:
    """
    Extract API endpoint definitions from source files.

    Args:
        files: List of FileContent objects to search

    Returns:
        List of EndpointInfo objects describing found endpoints
    """
    endpoints: list[EndpointInfo] = []

    for file in files:
        is_python = file.path.endswith(".py")
        is_js_ts = file.path.endswith((".js", ".jsx", ".ts", ".tsx"))

        # Python routes (only for .py files)
        if is_python:
            for pattern in PYTHON_ROUTE_PATTERNS:
                matches = re.finditer(pattern, file.content, re.IGNORECASE)
                for match in matches:
                    method = match.group("method").upper()
                    path = match.group("path")
                    # Try to find the function name
                    handler = _find_handler_name(file.content, match.end())
                    endpoints.append(
                        EndpointInfo(
                            method=method,
                            path=path,
                            file_path=file.path,
                            handler_name=handler,
                        )
                    )

        # JavaScript/TypeScript routes (only for .js/.ts files)
        if is_js_ts:
            for pattern in JS_ROUTE_PATTERNS:
                matches = re.finditer(pattern, file.content, re.IGNORECASE)
                for match in matches:
                    groups = match.groupdict()
                    method = groups.get("method", "GET").upper()
                    path = groups.get("path", "/")
                    endpoints.append(
                        EndpointInfo(
                            method=method,
                            path=path,
                            file_path=file.path,
                            handler_name=None,
                        )
                    )

    return endpoints


def _find_handler_name(content: str, start_pos: int) -> str | None:
    """
    Find the function name following a route decorator.

    Args:
        content: Full file content
        start_pos: Position after the decorator

    Returns:
        Function name if found, None otherwise
    """
    # Look for async def or def after the decorator
    match = re.search(r"(?:async\s+)?def\s+(\w+)", content[start_pos : start_pos + 200])
    return match.group(1) if match else None
