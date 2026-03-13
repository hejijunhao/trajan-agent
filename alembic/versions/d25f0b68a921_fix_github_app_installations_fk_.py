"""fix github_app_installations FK cascades for user delete

Revision ID: d25f0b68a921
Revises: l2g3h4i5j6k7
Create Date: 2026-03-13 10:16:44.878777

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd25f0b68a921'
down_revision: Union[str, None] = 'l2g3h4i5j6k7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('github_app_installations', 'installed_by_user_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.drop_constraint('github_app_installations_installed_by_user_id_fkey', 'github_app_installations', type_='foreignkey')
    op.drop_constraint('github_app_installations_organization_id_fkey', 'github_app_installations', type_='foreignkey')
    op.create_foreign_key('github_app_installations_installed_by_user_id_fkey', 'github_app_installations', 'users', ['installed_by_user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('github_app_installations_organization_id_fkey', 'github_app_installations', 'organizations', ['organization_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('github_app_installations_organization_id_fkey', 'github_app_installations', type_='foreignkey')
    op.drop_constraint('github_app_installations_installed_by_user_id_fkey', 'github_app_installations', type_='foreignkey')
    op.create_foreign_key('github_app_installations_organization_id_fkey', 'github_app_installations', 'organizations', ['organization_id'], ['id'])
    op.create_foreign_key('github_app_installations_installed_by_user_id_fkey', 'github_app_installations', 'users', ['installed_by_user_id'], ['id'])
    op.alter_column('github_app_installations', 'installed_by_user_id',
               existing_type=sa.UUID(),
               nullable=False)
