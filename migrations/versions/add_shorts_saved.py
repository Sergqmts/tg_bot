"""add shorts_saved table

Revision ID: add_shorts_saved
Revises:
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_shorts_saved'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'shorts_saved',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('shorts_id', sa.Integer(), sa.ForeignKey('shorts.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_shorts_saved_user_shorts', 'shorts_saved', ['user_id', 'shorts_id'], unique=True)


def downgrade():
    op.drop_index('ix_shorts_saved_user_shorts', table_name='shorts_saved')
    op.drop_table('shorts_saved')
