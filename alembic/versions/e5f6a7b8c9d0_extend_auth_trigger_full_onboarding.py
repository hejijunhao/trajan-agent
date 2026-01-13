"""extend_auth_trigger_full_onboarding

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-01-13 10:00:00.000000

This migration extends the auth.users trigger to create the full onboarding chain:
1. User record (already existed)
2. Personal organization (NEW)
3. Organization membership as OWNER (NEW)
4. Free-tier subscription (NEW)
5. Billing event audit log (NEW)

Previously, steps 2-5 only happened on the first API call (in deps.py).
This caused issues when users were created manually via Supabase dashboard,
as they would have no organization/subscription and fail on API calls.

Now, all downstream records are created atomically in the database trigger,
ensuring consistency regardless of how the user was created.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Replace the existing trigger function with extended version
    # that creates org, membership, subscription, and billing event
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

            -- Insert user record (same as before)
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
            -- Matches Python: re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + "-" + hex(3)
            v_random_suffix := encode(gen_random_bytes(3), 'hex');
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

            -- Create free-tier subscription (observer plan)
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

    # Grant permissions on new tables (trigger runs as supabase_auth_admin)
    op.execute("GRANT ALL ON public.organizations TO supabase_auth_admin")
    op.execute("GRANT ALL ON public.organization_members TO supabase_auth_admin")
    op.execute("GRANT ALL ON public.subscriptions TO supabase_auth_admin")
    op.execute("GRANT ALL ON public.billing_events TO supabase_auth_admin")


def downgrade() -> None:
    # Restore the original trigger function (user record only)
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

    # Revoke permissions (optional cleanup)
    op.execute("REVOKE ALL ON public.organizations FROM supabase_auth_admin")
    op.execute("REVOKE ALL ON public.organization_members FROM supabase_auth_admin")
    op.execute("REVOKE ALL ON public.subscriptions FROM supabase_auth_admin")
    op.execute("REVOKE ALL ON public.billing_events FROM supabase_auth_admin")
