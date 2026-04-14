"""Add privacy fields to user

Revision ID: 45ae55f5e3c3
Revises: 29c66ec1f247
Create Date: 2026-04-14 22:02:36.124848

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45ae55f5e3c3'
down_revision: Union[str, Sequence[str], None] = '29c66ec1f247'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user', sa.Column('is_private', sa.Boolean(), server_default='false'))
    op.add_column('user', sa.Column('hide_followers', sa.Boolean(), server_default='false'))
    op.add_column('user', sa.Column('hide_following', sa.Boolean(), server_default='false'))
    op.add_column('user', sa.Column('approve_followers', sa.Boolean(), server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user', 'approve_followers')
    op.drop_column('user', 'hide_following')
    op.drop_column('user', 'hide_followers')
    op.drop_column('user', 'is_private')
