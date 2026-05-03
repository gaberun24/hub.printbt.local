"""Rendelő modul page-route-jai (read-only Fázis 1.1-ben).

A Fázis 1.2-ben jönnek a CRUD route-ok (új igény, megrendelés,
megérkezés, kommentek). Most csak a lista + summary cards + szűrők.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.modules.rendelo.models import Category, Request, RequestStatus
from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import User, utcnow
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/rendelo", tags=["rendelo"])


def _summary(db: Session, user: User) -> dict:
    """A Rendelő-oldali 4 summary-card adata."""
    new_count = (
        db.execute(
            select(func.count()).select_from(Request).where(Request.status == RequestStatus.NEW)
        ).scalar()
        or 0
    )
    ordered_count = (
        db.execute(
            select(func.count()).select_from(Request).where(Request.status == RequestStatus.ORDERED)
        ).scalar()
        or 0
    )
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    arrived_month_count = (
        db.execute(
            select(func.count())
            .select_from(Request)
            .where(
                Request.status == RequestStatus.ARRIVED,
                Request.arrived_at >= month_start,
            )
        ).scalar()
        or 0
    )
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
    return {
        "new_count": new_count,
        "ordered_count": ordered_count,
        "arrived_month_count": arrived_month_count,
        "own_count": own_count,
    }


@router.get("", response_class=HTMLResponse)
def rendelo_list(
    request: FastAPIRequest,
    view: str | None = Query(None),
    category: int | None = Query(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """A Rendelő modul főoldala: aktív igények + utolsó hét megérkezett."""

    base_stmt = select(Request).options(
        selectinload(Request.lines),
        selectinload(Request.requested_by),
        selectinload(Request.ordered_by),
        selectinload(Request.category),
    )

    if category is not None:
        base_stmt = base_stmt.where(Request.category_id == category)
    if view == "own":
        base_stmt = base_stmt.where(Request.requested_by_id == user.id)

    active_stmt = base_stmt.where(
        Request.status.in_([RequestStatus.NEW, RequestStatus.ORDERED])
    ).order_by(Request.created_at.desc())
    active_requests = db.execute(active_stmt).scalars().all()

    arrived_cutoff = utcnow() - timedelta(days=7)
    arrived_stmt = (
        base_stmt.where(
            Request.status == RequestStatus.ARRIVED,
            Request.arrived_at >= arrived_cutoff,
        )
        .order_by(Request.arrived_at.desc())
        .limit(10)
    )
    arrived_requests = db.execute(arrived_stmt).scalars().all()

    active_category = None
    if category is not None:
        active_category = db.get(Category, category)

    return templates.TemplateResponse(
        request,
        "rendelo/list.html",
        {
            "user": user,
            "title": "Belső igények",
            "topbar_title": "Belső igények",
            "topbar_subtitle": "Toner, papír, alapanyag — fogyások és rendelések",
            "view": view,
            "active_category": active_category,
            "active_requests": active_requests,
            "arrived_requests": arrived_requests,
            "summary": _summary(db, user),
            **sidebar_context(db, user, active_key="rendelo_list"),
        },
    )
