"""rendelo_items: stock_qty, stock_fetched_at mezők (Malfini stock-szinkron)

Revision ID: 9c4d2e7b8f1a
Revises: f2a8b3c1d5e7
Create Date: 2026-05-05 15:00:00.000000+00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4d2e7b8f1a"
down_revision: str | None = "f2a8b3c1d5e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("rendelo_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("stock_qty", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("stock_fetched_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("rendelo_items", schema=None) as batch_op:
        batch_op.drop_column("stock_fetched_at")
        batch_op.drop_column("stock_qty")
