"""fix_auth_trigger_pending_subscription

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-01-25 19:45:00.000000

Updates the auth.users trigger to create subscriptions with:
- plan_tier = 'none' (instead of 'observer')
- status = 'pending' (instead of 'active')

This ensures new signups go through the plan selection flow instead of
automatically getting an active free-tier subscription.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Update auth trigger to create pending subscriptions."""
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS TRIGGER AS $$
        DECLARE
            v_user_id UUID;
            v_org_id UUID;
            v_org_name TEXT;
            v_org_slug TEXT;
            v_email_prefix TEXT;
            v_display_name TEXT;
            v_random_suffix TEXT;
        BEGIN
            -- Set user ID from auth.users
            v_user_id := NEW.id;

            -- Insert user record
            INSERT INTO public.users (id, email, github_username, avatar_url, created_at)
            VALUES (
                v_user_id,
                NEW.email,
                NEW.raw_user_meta_data->>'user_name',
                NEW.raw_user_meta_data->>'avatar_url',
                NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                github_username = COALESCE(EXCLUDED.github_username, public.users.github_username),
                avatar_url = COALESCE(EXCLUDED.avatar_url, public.users.avatar_url);

            -- Generate organization name from user metadata
            -- Priority: full_name > name > user_name > email prefix
            v_display_name := COALESCE(
                NEW.raw_user_meta_data->>'full_name',
                NEW.raw_user_meta_data->>'name',
                NEW.raw_user_meta_data->>'user_name',
                NULL
            );

            IF v_display_name IS NOT NULL AND v_display_name != '' THEN
                v_org_name := v_display_name || '''s Workspace';
            ELSIF NEW.email IS NOT NULL THEN
                v_email_prefix := split_part(NEW.email, '@', 1);
                v_org_name := v_email_prefix || '''s Workspace';
            ELSE
                v_org_name := 'My Workspace';
            END IF;

            -- Generate slug: lowercase, replace non-alphanumeric with hyphens, add random suffix
            -- Use substring of UUID instead of gen_random_bytes (pgcrypto not available in Supabase Auth context)
            v_random_suffix := substring(replace(gen_random_uuid()::text, '-', ''), 1, 6);
            v_org_slug := regexp_replace(lower(v_org_name), '[^a-z0-9]+', '-', 'g');
            v_org_slug := trim(BOTH '-' FROM v_org_slug);
            v_org_slug := v_org_slug || '-' || v_random_suffix;

            -- Generate new UUID for organization
            v_org_id := gen_random_uuid();

            -- Create personal organization
            INSERT INTO public.organizations (id, name, slug, owner_id, created_at)
            VALUES (v_org_id, v_org_name, v_org_slug, v_user_id, NOW());

            -- Create organization membership (user as OWNER)
            INSERT INTO public.organization_members (
                id, organization_id, user_id, role, joined_at
            )
            VALUES (
                gen_random_uuid(),
                v_org_id,
                v_user_id,
                'owner',
                NOW()
            );

            -- Create pending subscription (user must select a plan)
            -- plan_tier='none' and status='pending' trigger the plan selection flow
            INSERT INTO public.subscriptions (
                id,
                organization_id,
                plan_tier,
                status,
                base_repo_limit,
                created_at
            )
            VALUES (
                gen_random_uuid(),
                v_org_id,
                'none',
                'pending',
                0,
                NOW()
            );

            -- Log billing event for audit trail
            INSERT INTO public.billing_events (
                id,
                organization_id,
                event_type,
                description,
                new_value,
                created_at
            )
            VALUES (
                gen_random_uuid(),
                v_org_id,
                'subscription.created',
                'Pending subscription created on signup - awaiting plan selection',
                jsonb_build_object(
                    'plan_tier', 'none',
                    'status', 'pending',
                    'base_repo_limit', 0,
                    'source', 'auth_trigger'
                ),
                NOW()
            );

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)


def downgrade() -> None:
    """Restore trigger to create active free-tier subscriptions."""
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS TRIGGER AS $$
        DECLARE
            v_user_id UUID;
            v_org_id UUID;
            v_org_name TEXT;
            v_org_slug TEXT;
            v_email_prefix TEXT;
            v_display_name TEXT;
            v_random_suffix TEXT;
        BEGIN
            v_user_id := NEW.id;

            INSERT INTO public.users (id, email, github_username, avatar_url, created_at)
            VALUES (
                v_user_id,
                NEW.email,
                NEW.raw_user_meta_data->>'user_name',
                NEW.raw_user_meta_data->>'avatar_url',
                NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                github_username = COALESCE(EXCLUDED.github_username, public.users.github_username),
                avatar_url = COALESCE(EXCLUDED.avatar_url, public.users.avatar_url);

            v_display_name := COALESCE(
                NEW.raw_user_meta_data->>'full_name',
                NEW.raw_user_meta_data->>'name',
                NEW.raw_user_meta_data->>'user_name',
                NULL
            );

            IF v_display_name IS NOT NULL AND v_display_name != '' THEN
                v_org_name := v_display_name || '''s Workspace';
            ELSIF NEW.email IS NOT NULL THEN
                v_email_prefix := split_part(NEW.email, '@', 1);
                v_org_name := v_email_prefix || '''s Workspace';
            ELSE
                v_org_name := 'My Workspace';
            END IF;

            v_random_suffix := substring(replace(gen_random_uuid()::text, '-', ''), 1, 6);
            v_org_slug := regexp_replace(lower(v_org_name), '[^a-z0-9]+', '-', 'g');
            v_org_slug := trim(BOTH '-' FROM v_org_slug);
            v_org_slug := v_org_slug || '-' || v_random_suffix;

            v_org_id := gen_random_uuid();

            INSERT INTO public.organizations (id, name, slug, owner_id, created_at)
            VALUES (v_org_id, v_org_name, v_org_slug, v_user_id, NOW());

            INSERT INTO public.organization_members (
                id, organization_id, user_id, role, joined_at
            )
            VALUES (
                gen_random_uuid(),
                v_org_id,
                v_user_id,
                'owner',
                NOW()
            );

            INSERT INTO public.subscriptions (
                id,
                organization_id,
                plan_tier,
                status,
                base_repo_limit,
                created_at
            )
            VALUES (
                gen_random_uuid(),
                v_org_id,
                'observer',
                'active',
                1,
                NOW()
            );

            INSERT INTO public.billing_events (
                id,
                organization_id,
                event_type,
                description,
                new_value,
                created_at
            )
            VALUES (
                gen_random_uuid(),
                v_org_id,
                'subscription.created',
                'Free tier subscription created on signup',
                jsonb_build_object(
                    'plan_tier', 'observer',
                    'status', 'active',
                    'base_repo_limit', 1,
                    'source', 'auth_trigger'
                ),
                NOW()
            );

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)
