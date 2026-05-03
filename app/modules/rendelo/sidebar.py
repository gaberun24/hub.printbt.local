"""Rendelő modul-saját sidebar context — kategóriák és számlálók.

A Hub fő sidebarja (modul-szintű) marad a baloldalon. A Rendelőn belül
a kategória-szűrő egy second-level navigation, ami a fő tartalom
területén jelenik meg sticky filter-bar-ként vagy belső sub-sidebar-ként.

Ez a modul adja a kategória-számlálókat: hány nyitott (NEW + ORDERED)
igény van kategóriánként.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.rendelo.models import Category, Request, RequestStatus
from app.shared.models import User, utcnow

# Archív megjelenítési ablak: 2 év. A régebbi lezárt igények a DB-ben maradnak,
# csak a sidebar és a default archív nézet nem mutatja őket.
ARCHIVE_WINDOW_DAYS = 730


def rendelo_sidebar_context(db: Session, user: User) -> dict:
    """A Rendelő-oldalakon ezt **kiegészítésként** kell mergelni a fő
    `sidebar_context()` mellé."""

    categories = (
        db.execute(select(Category).order_by(Category.sort_order, Category.name)).scalars().all()
    )

    counts_rows = db.execute(
        select(Request.category_id, func.count())
        .where(Request.status.in_([RequestStatus.NEW, RequestStatus.ORDERED]))
        .group_by(Request.category_id)
    ).all()
    category_counts = dict(counts_rows)
    total_open = sum(category_counts.values())

    own_count = (
        db.execute(
            select(func.count())
            .select_from(Request)
            .where(
                Request.requested_by_id == user.id,
                Request.status.in_([RequestStatus.NEW, RequestStatus.ORDERED]),
            )
        ).scalar()
        or 0
    )

    assigned_count = (
        db.execute(
            select(func.count())
            .select_from(Request)
            .where(
                Request.ordered_by_id == user.id,
                Request.status == RequestStatus.ORDERED,
            )
        ).scalar()
        or 0
    )

    archive_cutoff = utcnow() - timedelta(days=ARCHIVE_WINDOW_DAYS)
    archive_count = (
        db.execute(
            select(func.count())
            .select_from(Request)
            .where(
                Request.status.in_([RequestStatus.ARRIVED, RequestStatus.CANCELLED]),
                Request.created_at >= archive_cutoff,
            )
        ).scalar()
        or 0
    )

    return {
        "rendelo_categories": categories,
        "rendelo_category_counts": category_counts,
        "rendelo_total_open": total_open,
        "rendelo_own_count": own_count,
        "rendelo_assigned_count": assigned_count,
        "rendelo_archive_count": archive_count,
    }
