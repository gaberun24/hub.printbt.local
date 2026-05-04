"""job_attachments: size_bytes, content_type, uploaded_by_id mezők

Revision ID: f2a8b3c1d5e7
Revises: c3a7f1b2e5d9
Create Date: 2026-05-04 18:30:00.000000+00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a8b3c1d5e7"
down_revision: str | None = "c3a7f1b2e5d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("jobs_attachments", schema=None, naming_convention=naming) as batch_op:
        batch_op.add_column(sa.Column("size_bytes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("content_type", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("uploaded_by_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_jobs_attachments_uploaded_by_id_users",
            "users",
            ["uploaded_by_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs_attachments", schema=None) as batch_op:
        batch_op.drop_constraint("fk_jobs_attachments_uploaded_by_id_users", type_="foreignkey")
        batch_op.drop_column("uploaded_by_id")
        batch_op.drop_column("content_type")
        batch_op.drop_column("size_bytes")
