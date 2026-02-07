"""
Codebase fingerprinting for documentation generation.

Computes a hash of the codebase state to detect when documentation
needs to be regenerated vs. when it can be skipped (unchanged codebase).
"""

import hashlib
import json
import logging

from app.services.docs.types import CodebaseContext

logger = logging.getLogger(__name__)


def compute_codebase_fingerprint(codebase_context: CodebaseContext) -> str:
    """
    Compute a fingerprint hash from codebase analysis results.

    The fingerprint captures:
    - Repository identities and branches
    - Total files and tokens analyzed
    - Detected patterns and tech stack
    - Key file paths (not content, to keep fingerprint stable)

    This allows skipping expensive AI generation when the codebase
    structure hasn't changed since the last generation.

    Args:
        codebase_context: The analyzed codebase context

    Returns:
        16-character hex fingerprint (truncated SHA-256)
    """
    # Build repo info for fingerprinting
    repo_info = [
        {
            "full_name": repo.full_name,
            "branch": repo.default_branch,
            "total_files": repo.total_files,
        }
        for repo in codebase_context.repositories
    ]
    repo_info.sort(key=lambda r: str(r["full_name"]))

    data = {
        # Repository identities
        "repos": repo_info,
        # Overall stats
        "total_files": codebase_context.total_files,
        "total_tokens": codebase_context.total_tokens,
        # Detected patterns (sorted for determinism)
        "patterns": sorted(codebase_context.detected_patterns),
        # Key file paths (not content, for stability)
        "key_files": sorted([f.path for f in codebase_context.all_key_files]),
        # Model count (structural indicator)
        "model_count": len(codebase_context.all_models),
        # Endpoint count (structural indicator)
        "endpoint_count": len(codebase_context.all_endpoints),
    }

    # Create deterministic JSON and hash it
    json_str = json.dumps(data, sort_keys=True)
    full_hash = hashlib.sha256(json_str.encode()).hexdigest()

    # Return first 16 chars (64 bits of entropy, enough for change detection)
    return full_hash[:16]


def should_skip_generation(
    current_fingerprint: str,
    stored_fingerprint: str | None,
) -> bool:
    """
    Check if documentation generation can be skipped.

    Args:
        current_fingerprint: Fingerprint of current codebase state
        stored_fingerprint: Fingerprint from last generation (if any)

    Returns:
        True if codebases match and generation can be skipped
    """
    if stored_fingerprint is None:
        logger.debug("No stored fingerprint, generation required")
        return False

    match = current_fingerprint == stored_fingerprint
    if match:
        logger.info(f"Codebase unchanged (fingerprint: {current_fingerprint}), skipping generation")
    else:
        logger.info(
            f"Codebase changed: {stored_fingerprint} -> {current_fingerprint}, regenerating"
        )

    return match
