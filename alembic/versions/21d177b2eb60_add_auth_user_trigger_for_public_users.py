"""add_auth_user_trigger_for_public_users

Revision ID: 21d177b2eb60
Revises: 2a20529ceef0
Create Date: 2026-01-07 19:42:45.685269

This migration creates a PostgreSQL trigger that automatically creates a
public.users record whenever a new user signs up via Supabase Auth.

Previously, public.users records were only created on the first API call
(in deps.py). This trigger ensures users exist immediately after signup,
which is more robust and allows for better data consistency.

The trigger extracts:
- id: from auth.users.id (UUID, same as Supabase auth user)
- email: from auth.users.email
- github_username: from raw_user_meta_data->>'user_name' (GitHub OAuth)
- avatar_url: from raw_user_meta_data->>'avatar_url' (OAuth providers)

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '21d177b2eb60'
down_revision: Union[str, None] = '2a20529ceef0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the function that will be called by the trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO public.users (id, email, github_username, avatar_url, created_at)
            VALUES (
                NEW.id,
                NEW.email,
                NEW.raw_user_meta_data->>'user_name',
                NEW.raw_user_meta_data->>'avatar_url',
                NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                github_username = COALESCE(EXCLUDED.github_username, public.users.github_username),
                avatar_url = COALESCE(EXCLUDED.avatar_url, public.users.avatar_url);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

    # Create the trigger on auth.users
    op.execute("""
        CREATE TRIGGER on_auth_user_created
            AFTER INSERT ON auth.users
            FOR EACH ROW
            EXECUTE FUNCTION public.handle_new_user();
    """)

    # Grant necessary permissions (separate statements for asyncpg compatibility)
    op.execute("GRANT USAGE ON SCHEMA public TO supabase_auth_admin")
    op.execute("GRANT ALL ON public.users TO supabase_auth_admin")


def downgrade() -> None:
    # Drop the trigger first
    op.execute("""
        DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
    """)

    # Drop the function
    op.execute("""
        DROP FUNCTION IF EXISTS public.handle_new_user();
    """)

    # Revoke permissions (optional, but clean)
    op.execute("""
        REVOKE ALL ON public.users FROM supabase_auth_admin;
    """)
