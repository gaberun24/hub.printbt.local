"""Globális oldalak: index/dashboard, healthcheck, modul placeholder-ek.

A modul-konkrét route-okat majd a `app/modules/<modul>/routes/` alatt
veszik át, ezek itt csak placeholder-ek a Fázis 0-hoz.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.shared.dependencies import current_user
from app.shared.models import User
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter()


@router.get("/health")
def healthcheck() -> JSONResponse:
    """Liveness check — az update-app.sh ezt pingeli a restart után."""
    return JSONResponse({"status": "ok"})


@router.get("/", response_class=HTMLResponse)
def index(request: Request, user: User = Depends(current_user)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "title": "Áttekintés",
            **sidebar_context(user, active_module=None),
        },
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_placeholder(request: Request, user: User = Depends(current_user)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "module_placeholder.html",
        {
            "user": user,
            "title": "Munkák",
            "module_label": "Munkák",
            "module_phase": "Fázis 2 — még nincs implementálva",
            **sidebar_context(user, active_module="jobs"),
        },
    )


@router.get("/rendelo", response_class=HTMLResponse)
def rendelo_placeholder(request: Request, user: User = Depends(current_user)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "module_placeholder.html",
        {
            "user": user,
            "title": "Rendelő",
            "module_label": "Rendelő",
            "module_phase": "Fázis 1 — migráció a meglévő nyomda_rendelo repóból",
            **sidebar_context(user, active_module="rendelo"),
        },
    )


@router.get("/stock", response_class=HTMLResponse)
def stock_placeholder(request: Request, user: User = Depends(current_user)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "module_placeholder.html",
        {
            "user": user,
            "title": "Készlet",
            "module_label": "Készlet",
            "module_phase": "Fázis 6 — még nincs implementálva",
            **sidebar_context(user, active_module="stock"),
        },
    )
