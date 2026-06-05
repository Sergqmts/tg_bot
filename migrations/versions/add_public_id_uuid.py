"""add public_id UUID to user, post, community

Revision ID: add_public_id_uuid
Revises: add_reset_token_and_onboarding_done
Create Date: 2026-06-05
"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'add_public_id_uuid'
down_revision = 'add_reset_token_and_onboarding_done'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    for table in ('user', 'post', 'community'):
        # Add column as nullable first so existing rows don't fail
        op.add_column(table, sa.Column('public_id', sa.String(36), nullable=True))

        # Back-fill existing rows with fresh UUIDs
        rows = conn.execute(text(f'SELECT id FROM "{table}"')).fetchall()
        for (row_id,) in rows:
            conn.execute(
                text(f'UPDATE "{table}" SET public_id = :uid WHERE id = :id'),
                {'uid': str(uuid.uuid4()), 'id': row_id},
            )

        # Make non-nullable and add unique index
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column('public_id', nullable=False)
            batch_op.create_unique_constraint(f'uq_{table}_public_id', ['public_id'])


def downgrade():
    for table in ('user', 'post', 'community'):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f'uq_{table}_public_id', type_='unique')
            batch_op.drop_column('public_id')
