"""simplify_auth_trigger_user_only

Revision ID: ca55440f0ab9
Revises: 416fdad32ded
Create Date: 2026-02-13 15:53:43.375812

Strips handle_new_user() down to only create the public.users record.
Removes organization, membership, subscription, and billing event creation
from the trigger. Org creation is now handled by the onboarding flow.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ca55440f0ab9'
down_revision: str | None = '416fdad32ded'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Insert user record only; org creation deferred to onboarding flow
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


def downgrade() -> None:
    """Restore full trigger that creates user + org + membership + subscription + billing event."""
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
                'none',
                'pending',
                0,
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
