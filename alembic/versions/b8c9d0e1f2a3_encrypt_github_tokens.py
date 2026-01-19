"""encrypt_github_tokens

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-01-19 20:00:00.000000

This migration encrypts existing plaintext GitHub tokens using Fernet encryption.
The encryption key must be set in the TOKEN_ENCRYPTION_KEY environment variable.

If no encryption key is configured, this migration is a no-op (tokens remain plaintext).
This allows for gradual rollout and testing.

IMPORTANT: Before running this migration in production:
1. Generate a new encryption key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
2. Store the key securely (secret manager, Fly.io secrets, etc.)
3. Set TOKEN_ENCRYPTION_KEY environment variable
4. Run this migration

After migration, new tokens will be encrypted automatically by the application layer.
"""
import os
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_encryption_key() -> str | None:
    """Get encryption key from environment."""
    return os.environ.get("TOKEN_ENCRYPTION_KEY", "").strip() or None


def _is_encrypted(value: str) -> bool:
    """Check if a value appears to be Fernet encrypted.

    Fernet tokens start with 'gAAAAA' and are typically 100+ characters.
    """
    return value.startswith("gAAAAA") and len(value) > 100


def upgrade() -> None:
    """Encrypt all existing plaintext GitHub tokens.

    Uses Fernet symmetric encryption. If no encryption key is configured,
    this migration is a no-op.
    """
    key = _get_encryption_key()
    if not key:
        print("TOKEN_ENCRYPTION_KEY not set - skipping token encryption.")
        print("To encrypt existing tokens, set the key and re-run this migration.")
        return

    try:
        from cryptography.fernet import Fernet
        cipher = Fernet(key.encode())
    except Exception as e:
        print(f"Invalid TOKEN_ENCRYPTION_KEY: {e}")
        print("Skipping token encryption. Fix the key and re-run.")
        return

    # Get database connection
    connection = op.get_bind()

    # Fetch all users with GitHub tokens
    result = connection.execute(
        text("SELECT user_id, github_token FROM user_preferences WHERE github_token IS NOT NULL")
    )
    rows = result.fetchall()

    encrypted_count = 0
    skipped_count = 0

    for row in rows:
        user_id = row[0]
        token = row[1]

        # Skip if already encrypted
        if _is_encrypted(token):
            skipped_count += 1
            continue

        # Encrypt the token
        encrypted_token = cipher.encrypt(token.encode()).decode()

        # Update the row
        connection.execute(
            text("UPDATE user_preferences SET github_token = :token WHERE user_id = :user_id"),
            {"token": encrypted_token, "user_id": user_id}
        )
        encrypted_count += 1

    print(f"Token encryption complete: {encrypted_count} encrypted, {skipped_count} already encrypted")


def downgrade() -> None:
    """Decrypt all encrypted GitHub tokens back to plaintext.

    WARNING: This exposes tokens in the database. Only use for rollback scenarios.
    """
    key = _get_encryption_key()
    if not key:
        print("TOKEN_ENCRYPTION_KEY not set - cannot decrypt tokens.")
        return

    try:
        from cryptography.fernet import Fernet
        cipher = Fernet(key.encode())
    except Exception as e:
        print(f"Invalid TOKEN_ENCRYPTION_KEY: {e}")
        return

    # Get database connection
    connection = op.get_bind()

    # Fetch all users with GitHub tokens
    result = connection.execute(
        text("SELECT user_id, github_token FROM user_preferences WHERE github_token IS NOT NULL")
    )
    rows = result.fetchall()

    decrypted_count = 0
    skipped_count = 0

    for row in rows:
        user_id = row[0]
        token = row[1]

        # Skip if not encrypted
        if not _is_encrypted(token):
            skipped_count += 1
            continue

        try:
            # Decrypt the token
            decrypted_token = cipher.decrypt(token.encode()).decode()

            # Update the row
            connection.execute(
                text("UPDATE user_preferences SET github_token = :token WHERE user_id = :user_id"),
                {"token": decrypted_token, "user_id": user_id}
            )
            decrypted_count += 1
        except Exception as e:
            print(f"Failed to decrypt token for user {user_id}: {e}")

    print(f"Token decryption complete: {decrypted_count} decrypted, {skipped_count} were plaintext")
