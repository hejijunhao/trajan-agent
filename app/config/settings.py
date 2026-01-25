from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database - transaction pooled connection for app operations (port 6543)
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:6543/postgres"
    # Database - direct connection for migrations (port 5432)
    database_url_direct: str = "postgresql+asyncpg://postgres:password@localhost:5432/postgres"

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwks_url: str = ""  # JWKS endpoint for ES256 JWT verification
    supabase_service_role_key: str = ""  # Service role key for admin operations (user invites)

    # Application
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]
    frontend_url: str = "http://localhost:3000"  # For constructing shareable URLs

    # AI / Anthropic
    anthropic_api_key: str = ""

    # Security - Encryption key for sensitive data at rest (GitHub tokens, etc.)
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = ""

    # Stripe - Payment processing
    # Use sk_test_*/pk_test_* for development, sk_live_*/pk_live_* for production
    # Empty string = Stripe disabled (feature gating still works, just no payments)
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""  # From `stripe listen` (dev) or Stripe Dashboard (prod)

    # Stripe Price IDs - Create these in Stripe Dashboard (test mode for dev, live for prod)
    # Tier base prices (monthly subscriptions)
    stripe_price_indie_base: str = ""
    stripe_price_pro_base: str = ""
    stripe_price_scale_base: str = ""
    # Single overage price for all tiers ($10/repo)
    stripe_price_repo_overage: str = ""

    # Stripe Meter ID for repo overage (from Stripe Dashboard)
    stripe_meter_id: str = ""

    @property
    def stripe_enabled(self) -> bool:
        """Check if Stripe is configured (has secret key)."""
        return bool(self.stripe_secret_key)


settings = Settings()
