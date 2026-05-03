"""Globális oldalak: index/dashboard, healthcheck, modul placeholder-ek.

A modul-konkrét route-okat majd a `app/modules/<modul>/routes/` alatt
veszik át — ezek itt placeholder-ek azokhoz a sidebar-elemekhez,
amelyeknek még nincs saját moduljuk.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import User, utcnow
from app.shared.sidebar import sidebar_context
from app.shared.templates import _hu_date, templates

router = APIRouter()


@router.get("/health")
def healthcheck() -> JSONResponse:
    """Liveness check — az update-app.sh ezt pingeli a restart után."""
    return JSONResponse({"status": "ok"})


def _dashboard_stats(db: Session, user: User) -> dict:
    """A dashboard 4 stat-cardjához gyűjt adatot."""
    from app.modules.rendelo.models import Request as RendeloRequest
    from app.modules.rendelo.models import RequestStatus

    rendelo_open = (
        db.execute(
            select(func.count())
            .select_from(RendeloRequest)
            .where(RendeloRequest.status.in_([RequestStatus.NEW, RequestStatus.ORDERED]))
        ).scalar()
        or 0
    )
    rendelo_own = (
        db.execute(
            select(func.count())
            .select_from(RendeloRequest)
            .where(
                RendeloRequest.requested_by_id == user.id,
                RendeloRequest.status.in_([RequestStatus.NEW, RequestStatus.ORDERED]),
            )
        ).scalar()
        or 0
    )
    rendelo_ordered = (
        db.execute(
            select(func.count())
            .select_from(RendeloRequest)
            .where(RendeloRequest.status == RequestStatus.ORDERED)
        ).scalar()
        or 0
    )
    users_active = (
        db.execute(select(func.count()).select_from(User).where(User.active.is_(True))).scalar()
        or 0
    )
    return {
        "rendelo_open": rendelo_open,
        "rendelo_own": rendelo_own,
        "rendelo_ordered": rendelo_ordered,
        "users": users_active,
    }


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "title": "Áttekintés",
            "topbar_title": "Áttekintés",
            "today_human": _hu_date(utcnow(), "long"),
            "stats": _dashboard_stats(db, user),
            **sidebar_context(db, user, active_key=None),
        },
    )


def _placeholder_response(
    request: Request,
    user: User,
    db: Session,
    *,
    title: str,
    phase: str,
    active_key: str,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "module_placeholder.html",
        {
            "user": user,
            "title": title,
            "topbar_title": title,
            "module_label": title,
            "module_phase": phase,
            **sidebar_context(db, user, active_key=active_key),
        },
    )


@router.get("/jobs/workshop", response_class=HTMLResponse)
def jobs_workshop(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _placeholder_response(
        request,
        user,
        db,
        title="Műhely",
        phase="Fázis 2 — task-listák gép szerint",
        active_key="jobs_workshop",
    )


@router.get("/jobs/inbox", response_class=HTMLResponse)
def jobs_inbox(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _placeholder_response(
        request,
        user,
        db,
        title="Bejövő posta",
        phase="Fázis 4 — IMAP poller + Gemini előszűrés",
        active_key="jobs_inbox",
    )


@router.get("/jobs/quotes", response_class=HTMLResponse)
def jobs_quotes(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _placeholder_response(
        request,
        user,
        db,
        title="Árajánlatok",
        phase="Fázis 5 — shared inbox lock + Gemini draft",
        active_key="jobs_quotes",
    )


@router.get("/stock", response_class=HTMLResponse)
def stock_placeholder(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _placeholder_response(
        request,
        user,
        db,
        title="Készlet",
        phase="Fázis 6 — stock_items + min-stock figyelő",
        active_key="stock_list",
    )


@router.get("/sheet", response_class=HTMLResponse)
def sheet_placeholder(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _placeholder_response(
        request,
        user,
        db,
        title="Munkalap",
        phase="Fázis 3 — WeasyPrint A4 generálás",
        active_key="data_sheet",
    )
