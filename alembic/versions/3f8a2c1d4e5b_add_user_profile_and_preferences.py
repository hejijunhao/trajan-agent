"""add_user_profile_and_preferences

Revision ID: 3f8a2c1d4e5b
Revises: 21d177b2eb60
Create Date: 2026-01-07 22:00:00.000000

This migration:
1. Adds display_name, auth_provider, updated_at columns to users table
2. Creates user_preferences table for notification and UI settings
3. Updates the auth trigger to include auth_provider

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '3f8a2c1d4e5b'
down_revision: Union[str, None] = '21d177b2eb60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to users table
    op.add_column('users', sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True))
    op.add_column('users', sa.Column('auth_provider', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(), nullable=True))

    # Create user_preferences table
    op.create_table('user_preferences',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('email_digest', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default='none'),
        sa.Column('notify_work_items', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('notify_documents', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('github_token', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('default_view', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default='grid'),
        sa.Column('sidebar_default', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default='expanded'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
    )

    # Update the auth trigger function to include auth_provider
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS TRIGGER AS $$
        DECLARE
            provider_name TEXT;
        BEGIN
            -- Determine auth provider from app_metadata or identities
            provider_name := NEW.raw_app_meta_data->>'provider';
            IF provider_name IS NULL THEN
                provider_name := 'email';
            END IF;

            INSERT INTO public.users (id, email, github_username, avatar_url, auth_provider, created_at)
            VALUES (
                NEW.id,
                NEW.email,
                NEW.raw_user_meta_data->>'user_name',
                NEW.raw_user_meta_data->>'avatar_url',
                provider_name,
                NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                github_username = COALESCE(EXCLUDED.github_username, public.users.github_username),
                avatar_url = COALESCE(EXCLUDED.avatar_url, public.users.avatar_url),
                auth_provider = COALESCE(public.users.auth_provider, EXCLUDED.auth_provider),
                updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)


def downgrade() -> None:
    # Revert auth trigger to original version
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

    # Drop user_preferences table
    op.drop_table('user_preferences')

    # Remove columns from users table
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'auth_provider')
    op.drop_column('users', 'display_name')
