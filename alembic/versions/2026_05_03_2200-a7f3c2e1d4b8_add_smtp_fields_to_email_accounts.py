"""add smtp fields to email_accounts

Revision ID: a7f3c2e1d4b8
Revises: d14ea8a8be12
Create Date: 2026-05-03 22:00:00.000000+00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = 'a7f3c2e1d4b8'
down_revision: str | Sequence[str] | None = 'd14ea8a8be12'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('email_accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('smtp_host', sa.String(200), nullable=True))
        batch_op.add_column(sa.Column('smtp_port', sa.Integer(), server_default='587', nullable=False))
        batch_op.add_column(sa.Column('smtp_user', sa.String(200), nullable=True))
        batch_op.add_column(sa.Column('smtp_password_encrypted', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('smtp_use_tls', sa.Boolean(), server_default='1', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('email_accounts', schema=None) as batch_op:
        batch_op.drop_column('smtp_use_tls')
        batch_op.drop_column('smtp_password_encrypted')
        batch_op.drop_column('smtp_user')
        batch_op.drop_column('smtp_port')
        batch_op.drop_column('smtp_host')
