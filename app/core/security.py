"""Security utilities for token generation and validation."""

import secrets


def generate_quick_access_token() -> str:
    """Generate a cryptographically secure URL-safe token for quick access links.

    Returns a 43-character URL-safe string with 256 bits of entropy.
    """
    return secrets.token_urlsafe(32)
