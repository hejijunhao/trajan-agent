"""Encryption utilities for sensitive data at rest.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256).
The encryption key must be a 32-byte URL-safe base64-encoded string.

Generate a new key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


class TokenEncryption:
    """Handles encryption/decryption of sensitive tokens.

    Provides a simple interface for encrypting and decrypting strings
    using Fernet symmetric encryption. Designed for encrypting GitHub
    tokens and other sensitive credentials stored in the database.

    The encryption key is loaded from settings.token_encryption_key.
    If no key is configured, encryption operations are disabled and
    plaintext values pass through unchanged (for backwards compatibility
    during migration).
    """

    def __init__(self) -> None:
        self._cipher: Fernet | None = None
        self._key_configured = False

        key = settings.token_encryption_key
        if key:
            try:
                self._cipher = Fernet(key.encode())
                self._key_configured = True
            except (ValueError, TypeError):
                logger.warning("token_encryption_key has invalid format — encryption disabled")
        elif not settings.debug:
            logger.warning(
                "SECURITY: token_encryption_key is not configured. "
                "Sensitive tokens (GitHub, etc.) will be stored in plaintext."
            )

    @property
    def is_enabled(self) -> bool:
        """Check if encryption is properly configured."""
        return self._key_configured and self._cipher is not None

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string.

        Args:
            plaintext: The string to encrypt.

        Returns:
            The encrypted string (URL-safe base64 encoded).
            If encryption is not enabled, returns the plaintext unchanged.
        """
        if not self.is_enabled or not self._cipher:
            return plaintext

        return self._cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted string.

        Args:
            ciphertext: The encrypted string to decrypt.

        Returns:
            The decrypted plaintext string.
            If encryption is not enabled, returns the ciphertext unchanged.

        Note:
            If decryption fails (e.g., the value was stored in plaintext
            before encryption was enabled), returns the original value.
            This provides backwards compatibility during migration.
        """
        if not self.is_enabled or not self._cipher:
            return ciphertext

        try:
            return self._cipher.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            # Value may be stored in plaintext (pre-encryption)
            # Return as-is for backwards compatibility
            return ciphertext

    def is_encrypted(self, value: str) -> bool:
        """Check if a value appears to be encrypted.

        Fernet tokens have a specific format: start with 'gAAAAA'.
        This helps identify plaintext vs encrypted values during migration.
        """
        return value.startswith("gAAAAA") and len(value) > 100


# Singleton instance for application-wide use
token_encryption = TokenEncryption()
