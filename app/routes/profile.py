"""Felhasználói profil beállítások: avatar testreszabás és jelszóváltás."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import User
from app.shared.security import hash_password, verify_password
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter()

# Hex szín regex — #RGB vagy #RRGGBB formátum
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def _profile_ctx(
    request: Request,
    user: User,
    db: Session,
    *,
    avatar_saved: bool = False,
    pw_saved: bool = False,
    pw_error: str | None = None,
) -> dict:
    """Közös template-kontextus a profil oldalhoz."""
    return {
        "user": user,
        "title": "Beállítások",
        "topbar_title": "Beállítások",
        "avatar_saved": avatar_saved,
        "pw_saved": pw_saved,
        "pw_error": pw_error,
        **sidebar_context(db, user, active_key=None),
    }


@router.get("/profile", response_class=HTMLResponse)
def profile_page(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "profile.html",
        _profile_ctx(request, user, db),
    )


@router.post("/profile/avatar")
def profile_avatar(
    request: Request,
    initials: str = Form(""),
    color: str = Form("default"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    # Betűk: max 4 karakter, uppercase, strip
    clean_initials = initials.strip().upper()[:4] or None

    # Szín: bármilyen valid hex color elfogadva, egyébként NULL (gradient)
    clean_color = color.strip() if _HEX_COLOR_RE.match(color.strip()) else None

    user.avatar_initials = clean_initials
    user.avatar_color = clean_color
    db.commit()

    return templates.TemplateResponse(
        request,
        "profile.html",
        _profile_ctx(request, user, db, avatar_saved=True),
    )


@router.post("/profile/password")
def profile_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    # Validáció
    error: str | None = None

    if not verify_password(current_password, user.password_hash):
        error = "A jelenlegi jelszó helytelen."
    elif len(new_password) < 8:
        error = "Az új jelszó legalább 8 karakter legyen."
    elif new_password != confirm_password:
        error = "A két új jelszó nem egyezik."

    if error:
        return templates.TemplateResponse(
            request,
            "profile.html",
            _profile_ctx(request, user, db, pw_error=error),
        )

    user.password_hash = hash_password(new_password)
    db.commit()

    return templates.TemplateResponse(
        request,
        "profile.html",
        _profile_ctx(request, user, db, pw_saved=True),
    )
