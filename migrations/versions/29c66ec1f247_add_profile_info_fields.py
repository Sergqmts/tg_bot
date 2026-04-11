"""add profile info fields

Revision ID: 29c66ec1f247
Revises: 
Create Date: 2026-04-11 10:23:57.122844

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29c66ec1f247'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user', sa.Column('location', sa.String(length=100), nullable=True))
    op.add_column('user', sa.Column('website', sa.String(length=200), nullable=True))
    op.add_column('user', sa.Column('birthday', sa.Date(), nullable=True))
    op.add_column('user', sa.Column('interests', sa.Text(), nullable=True))
    op.add_column('user', sa.Column('occupation', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user', 'occupation')
    op.drop_column('user', 'interests')
    op.drop_column('user', 'birthday')
    op.drop_column('user', 'website')
    op.drop_column('user', 'location')
