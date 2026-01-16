"""Supabase admin client for server-side operations."""

from supabase import Client, create_client

from app.config.settings import settings


def get_supabase_admin_client() -> Client:
    """
    Get Supabase client with service role key for admin operations.

    This client has elevated privileges and should only be used for:
    - Creating/inviting users via admin API
    - Other admin-only operations

    IMPORTANT: Never expose this client to frontend or use anon key here.
    """
    if not settings.supabase_service_role_key:
        raise ValueError(
            "SUPABASE_SERVICE_ROLE_KEY not configured. "
            "Set it in .env for user invite functionality."
        )

    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
