"""add_auth_user_delete_cascade_trigger

Revision ID: 6282be877602
Revises: 6f3e68cd3804
Create Date: 2026-02-26 18:10:59.312932

Adds a BEFORE DELETE trigger on auth.users that cascades deletion to
public.users (and all FK-dependent rows). Blocks deletion if the user
owns any organization with other members — ownership must be transferred
or members removed first.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6282be877602'
down_revision: Union[str, None] = '6f3e68cd3804'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_user_deleted()
        RETURNS TRIGGER AS $$
        DECLARE
            v_multi_member_org RECORD;
        BEGIN
            -- Block deletion if user owns any org with other members
            SELECT o.id, o.name
              INTO v_multi_member_org
              FROM public.organizations o
              JOIN public.organization_members om ON om.organization_id = o.id
             WHERE o.owner_id = OLD.id
             GROUP BY o.id, o.name
            HAVING COUNT(om.id) > 1
             LIMIT 1;

            IF FOUND THEN
                RAISE EXCEPTION
                    'Cannot delete user %: owns organization "%" with other members. '
                    'Transfer ownership or remove members first.',
                    OLD.id, v_multi_member_org.name;
            END IF;

            -- Delete solo-owned organizations (CASCADE handles products,
            -- subscriptions, members, billing events, etc.)
            DELETE FROM public.organizations
             WHERE owner_id = OLD.id;

            -- Delete the public.users row (CASCADE handles preferences,
            -- memberships in other orgs, product_access, referral_codes,
            -- feedback, etc.)
            DELETE FROM public.users WHERE id = OLD.id;

            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

    op.execute("""
        CREATE TRIGGER on_auth_user_deleted
            BEFORE DELETE ON auth.users
            FOR EACH ROW
            EXECUTE FUNCTION public.handle_user_deleted();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS on_auth_user_deleted ON auth.users;")
    op.execute("DROP FUNCTION IF EXISTS public.handle_user_deleted();")
