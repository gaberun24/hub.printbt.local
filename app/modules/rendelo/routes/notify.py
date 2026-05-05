"""Rendelő modul live-notification poll endpoint.

A kliensoldali htmx 60 mp-enként hívja, és a szerver:
1. Visszaadja a sidebar belsejét (számok auto-frissülése)
2. HX-Trigger header-ben jelez ha új igény van — `rendelo_notify.js` reagál
   (toast + Web Audio ding) — csak `is_orderer` / `is_admin`-nek.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.rendelo.models import Request, RequestStatus
from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import User
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/rendelo/notify", tags=["rendelo-notify"])


@router.get("/poll", response_class=HTMLResponse)
def poll(
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Sidebar inner HTML + HX-Trigger event a kliensnek."""
    notify_payload: dict = {"latest_id": 0, "latest_title": None}

    if user.is_orderer or user.is_admin:
        latest = db.execute(
            select(Request)
            .where(
                Request.status == RequestStatus.NEW,
                Request.requested_by_id != user.id,
            )
            .order_by(Request.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is not None:
            first_line_title = latest.lines[0].title if latest.lines else "?"
            extra = f" + {len(latest.lines) - 1} tétel" if len(latest.lines) > 1 else ""
            notify_payload = {
                "latest_id": latest.id,
                "latest_title": f"{first_line_title}{extra}",
            }

    # A teljes <aside class="sidebar"> újra-renderolása — htmx outerHTML-szel
    # cseréli a meglévőt. A polling-div is benne marad, így folytatódik.
    response = templates.TemplateResponse(
        request,
        "partials/_sidebar.html",
        {
            "user": user,
            **sidebar_context(db, user),
        },
    )
    response.headers["HX-Trigger"] = json.dumps({"rendelo:poll": notify_payload})
    response.headers["Cache-Control"] = "no-store"
    return response
