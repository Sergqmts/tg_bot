"""Add Shorts models

Revision ID: add_shorts
Revises: 
Create Date: 2026-04-26

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_shorts'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('shorts_audio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('audio_url', sa.String(length=500), nullable=False),
        sa.Column('duration', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], )
    )
    op.create_table('shorts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('video_url', sa.String(length=500), nullable=False),
        sa.Column('audio_id', sa.Integer(), nullable=True),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('views', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['audio_id'], ['shorts_audio.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], )
    )
    op.create_table('shorts_like',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('shorts_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['shorts_id'], ['shorts.id'], )
    )
    op.create_table('shorts_comment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('shorts_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['shorts_id'], ['shorts.id'], )
    )

def downgrade():
    op.drop_table('shorts_comment')
    op.drop_table('shorts_like')
    op.drop_table('shorts')
    op.drop_table('shorts_audio')