"""add is_outgoing, sent_by_user_id to incoming_emails

Revision ID: c3a7f1b2e5d9
Revises: a7f3c2e1d4b8
Create Date: 2026-05-03 23:15:00.000000+00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = 'c3a7f1b2e5d9'
down_revision: str | Sequence[str] | None = 'a7f3c2e1d4b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table('incoming_emails', schema=None, naming_convention=naming) as batch_op:
        batch_op.add_column(sa.Column('is_outgoing', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('sent_by_user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_incoming_emails_sent_by_user_id_users',
            'users', ['sent_by_user_id'], ['id'], ondelete='SET NULL',
        )


def downgrade() -> None:
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table('incoming_emails', schema=None, naming_convention=naming) as batch_op:
        batch_op.drop_constraint('fk_incoming_emails_sent_by_user_id_users', type_='foreignkey')
        batch_op.drop_column('sent_by_user_id')
        batch_op.drop_column('is_outgoing')
