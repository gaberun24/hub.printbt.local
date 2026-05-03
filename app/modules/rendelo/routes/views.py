"""Rendelő modul page-route-jai (read-only Fázis 1.1-ben).

A Fázis 1.2-ben jönnek a CRUD route-ok (új igény, megrendelés,
megérkezés, kommentek). Most csak a lista + szűrők menjenek.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modules.rendelo.models import Category, Request, RequestStatus
from app.modules.rendelo.sidebar import rendelo_sidebar_context
from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import User
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/rendelo", tags=["rendelo"])


@router.get("", response_class=HTMLResponse)
def rendelo_list(
    request: FastAPIRequest,
    view: str | None = Query(None, description="own | assigned | archive | None (mind nyitott)"),
    category: int | None = Query(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """A Rendelő modul főoldala: nyitott igények listája szűrőkkel."""

    stmt = select(Request).options(
        selectinload(Request.lines),
        selectinload(Request.requested_by),
        selectinload(Request.ordered_by),
        selectinload(Request.category),
    )

    if view == "own":
        stmt = stmt.where(
            Request.requested_by_id == user.id,
            Request.status.in_([RequestStatus.NEW, RequestStatus.ORDERED]),
        )
        view_label = "Saját nyitott igényeim"
    elif view == "assigned":
        stmt = stmt.where(
            Request.ordered_by_id == user.id,
            Request.status == RequestStatus.ORDERED,
        )
        view_label = "Általam megrendelve"
    elif view == "archive":
        stmt = stmt.where(Request.status.in_([RequestStatus.ARRIVED, RequestStatus.CANCELLED]))
        view_label = "Archív"
    else:
        stmt = stmt.where(Request.status.in_([RequestStatus.NEW, RequestStatus.ORDERED]))
        view_label = "Minden nyitott igény"

    if category is not None:
        stmt = stmt.where(Request.category_id == category)

    stmt = stmt.order_by(Request.created_at.desc())
    requests = db.execute(stmt).scalars().all()

    active_category = None
    if category is not None:
        active_category = db.get(Category, category)

    return templates.TemplateResponse(
        request,
        "rendelo/list.html",
        {
            "user": user,
            "title": f"Rendelő — {view_label}",
            "view": view,
            "view_label": view_label,
            "active_category": active_category,
            "requests": requests,
            **sidebar_context(user, active_module="rendelo"),
            **rendelo_sidebar_context(db, user),
        },
    )
