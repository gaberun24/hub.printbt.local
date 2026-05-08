"""customers: public_id mező + meglevő rekordok backfillje

Revision ID: d8e3f4a5b6c1
Revises: 9c4d2e7b8f1a
Create Date: 2026-05-05 20:00:00.000000+00:00

"""
from __future__ import annotations

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8e3f4a5b6c1"
down_revision: str | None = "9c4d2e7b8f1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Customer public_id formátum: 2 betű + 3 szám (XX###), kötőjel nélkül.
# Pl. "KM472", "HB019". A vizuálisan zavaró I/L/O/U kihagyva.
LETTERS = "ABCDEFGHJKMNPQRSTVWXYZ"
DIGITS = "0123456789"


def _gen() -> str:
    letters = "".join(secrets.choice(LETTERS) for _ in range(2))
    digits = "".join(secrets.choice(DIGITS) for _ in range(3))
    return letters + digits


def upgrade() -> None:
    # 1. Mező hozzáadása nullable=True-val (a meglévő sorok ekkor még NULL-t kapnak)
    with op.batch_alter_table("customers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("public_id", sa.String(8), nullable=True))
        batch_op.create_index(
            "ix_customers_public_id", ["public_id"], unique=True
        )

    # 2. Backfill: minden meglévő Customer-nek generálunk egyedi public_id-t.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id FROM customers WHERE public_id IS NULL")
    ).fetchall()

    used: set[str] = set()
    # Meglévő kollíziókat is megnézzük (másik migráció után esetleg)
    pre_existing = bind.execute(
        sa.text("SELECT public_id FROM customers WHERE public_id IS NOT NULL")
    ).fetchall()
    for (pid,) in pre_existing:
        if pid:
            used.add(pid)

    for (cid,) in rows:
        candidate = None
        for _ in range(50):  # max 50 retry
            c = _gen()
            if c not in used:
                candidate = c
                break
        if candidate is None:
            # +1 számjegy ha kifutottunk az 5-karakteres térből
            for _ in range(50):
                c = _gen() + secrets.choice(DIGITS)
                if c not in used:
                    candidate = c
                    break
        if candidate is None:
            raise RuntimeError(f"Customer #{cid} public_id generálás sikertelen")
        used.add(candidate)
        bind.execute(
            sa.text("UPDATE customers SET public_id = :pid WHERE id = :id"),
            {"pid": candidate, "id": cid},
        )


def downgrade() -> None:
    with op.batch_alter_table("customers", schema=None) as batch_op:
        batch_op.drop_index("ix_customers_public_id")
        batch_op.drop_column("public_id")
