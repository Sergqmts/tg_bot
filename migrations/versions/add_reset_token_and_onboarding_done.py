"""add_reset_token_and_onboarding_done

Revision ID: add_reset_token_and_onboarding_done
Revises: add_transcription_to_message, add_is_archived_to_event, add_shorts, add_shorts_saved
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_reset_token_and_onboarding_done'
down_revision = ('add_transcription_to_message', 'add_is_archived_to_event', 'add_shorts', 'add_shorts_saved')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('reset_token', sa.String(64), nullable=True))
    op.add_column('user', sa.Column('reset_token_expires', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('onboarding_done', sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade():
    op.drop_column('user', 'onboarding_done')
    op.drop_column('user', 'reset_token_expires')
    op.drop_column('user', 'reset_token')
