"""Add is_archived to CommunityEvent

Revision ID: add_is_archived_to_event
Revises:
Create Date: 2026-04-26

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_is_archived_to_event'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('community_event', sa.Column('is_archived', sa.Boolean(), default=False))

def downgrade():
    op.drop_column('community_event', 'is_archived')