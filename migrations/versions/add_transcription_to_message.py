"""Add transcription to message

Revision ID: add_transcription_to_message
Revises: 45ae55f5e3c3
Create Date: 2026-04-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_transcription_to_message'
down_revision = '45ae55f5e3c3'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('message', sa.Column('transcription', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('message', 'transcription')