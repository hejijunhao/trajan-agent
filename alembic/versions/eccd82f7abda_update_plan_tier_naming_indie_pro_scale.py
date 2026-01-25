"""update_plan_tier_naming_indie_pro_scale

Revision ID: eccd82f7abda
Revises: d3fa1864408b
Create Date: 2026-01-25 16:42:19.812691

Migrates plan tier names from legacy naming (observer/foundations/core/autonomous)
to new naming (indie/pro/scale) for consistency with the updated pricing model.

Updates:
- subscriptions.plan_tier: Map old tier names to new names
- subscriptions.plan_tier server_default: 'observer' -> 'indie'
- usage_snapshots.plan_tier: Map old tier names to new names (historical data)
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eccd82f7abda"
down_revision: Union[str, None] = "d3fa1864408b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Migrate plan tier names to new Indie/Pro/Scale naming."""

    # Step 1: Update existing subscriptions to use new tier names
    # observer, foundations -> indie
    # core -> pro
    # autonomous -> scale
    op.execute(
        """
        UPDATE subscriptions
        SET plan_tier = CASE plan_tier
            WHEN 'observer' THEN 'indie'
            WHEN 'foundations' THEN 'indie'
            WHEN 'core' THEN 'pro'
            WHEN 'autonomous' THEN 'scale'
            ELSE plan_tier
        END
        WHERE plan_tier IN ('observer', 'foundations', 'core', 'autonomous')
        """
    )

    # Step 2: Update usage_snapshots historical data
    op.execute(
        """
        UPDATE usage_snapshots
        SET plan_tier = CASE plan_tier
            WHEN 'observer' THEN 'indie'
            WHEN 'foundations' THEN 'indie'
            WHEN 'core' THEN 'pro'
            WHEN 'autonomous' THEN 'scale'
            ELSE plan_tier
        END
        WHERE plan_tier IN ('observer', 'foundations', 'core', 'autonomous')
        """
    )

    # Step 3: Update server_default for new subscriptions
    op.alter_column(
        "subscriptions",
        "plan_tier",
        server_default="indie",
    )

    # Step 4: Update base_repo_limit for indie tier (was 1 for observer, now 5)
    op.execute(
        """
        UPDATE subscriptions
        SET base_repo_limit = 5
        WHERE plan_tier = 'indie' AND base_repo_limit < 5
        """
    )


def downgrade() -> None:
    """Revert to legacy tier naming (not recommended)."""

    # Revert server_default
    op.alter_column(
        "subscriptions",
        "plan_tier",
        server_default="observer",
    )

    # Revert tier names in subscriptions
    op.execute(
        """
        UPDATE subscriptions
        SET plan_tier = CASE plan_tier
            WHEN 'indie' THEN 'observer'
            WHEN 'pro' THEN 'core'
            WHEN 'scale' THEN 'autonomous'
            ELSE plan_tier
        END
        WHERE plan_tier IN ('indie', 'pro', 'scale')
        """
    )

    # Revert tier names in usage_snapshots
    op.execute(
        """
        UPDATE usage_snapshots
        SET plan_tier = CASE plan_tier
            WHEN 'indie' THEN 'observer'
            WHEN 'pro' THEN 'core'
            WHEN 'scale' THEN 'autonomous'
            ELSE plan_tier
        END
        WHERE plan_tier IN ('indie', 'pro', 'scale')
        """
    )

    # Revert base_repo_limit
    op.execute(
        """
        UPDATE subscriptions
        SET base_repo_limit = 1
        WHERE plan_tier = 'observer' AND base_repo_limit = 5
        """
    )
