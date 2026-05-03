"""Authentikáció: login, logout, meghívó-beváltás. Modul-független, az
egész app-ra érvényes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.auth import (
    SESSION_COOKIE_NAME,
    authenticate,
    create_session,
    destroy_session,
)
from app.shared.config import settings
from app.shared.db import get_db
from app.shared.dependencies import current_session
from app.shared.models import ROLE_FLAGS, Invite, User, UserSession, utcnow
from app.shared.security import hash_password
from app.shared.templates import templates

router = APIRouter()


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=settings.session_lifetime_days * 24 * 3600,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": None, "email": ""},
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    user = authenticate(db, email, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Helytelen email vagy jelszó.", "email": email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    raw_token = create_session(
        db,
        user,
        user_agent=request.headers.get("user-agent"),
        ip=(request.client.host if request.client else None),
    )
    db.commit()
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, raw_token)
    return response


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        destroy_session(db, raw_token)
        db.commit()
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/invite/{token}", response_class=HTMLResponse)
def invite_form(token: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    invite = _load_invite(db, token)
    if invite is None:
        return templates.TemplateResponse(
            request, "auth/invite_invalid.html", {}, status_code=status.HTTP_410_GONE
        )
    return templates.TemplateResponse(
        request,
        "auth/invite_redeem.html",
        {
            "invite": invite,
            "error": None,
            "name": "",
            "email": invite.email_hint or "",
            "active_flags": [f for f in ROLE_FLAGS if getattr(invite, f)],
        },
    )


@router.post("/invite/{token}")
def invite_submit(
    token: str,
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    invite = _load_invite(db, token)
    if invite is None:
        return templates.TemplateResponse(
            request, "auth/invite_invalid.html", {}, status_code=status.HTTP_410_GONE
        )

    error: str | None = None
    if password != password_confirm:
        error = "A két jelszó nem egyezik."
    elif len(password) < 10:
        error = "A jelszó legalább 10 karakter legyen."
    elif not name.strip():
        error = "Add meg a nevedet."
    elif not email.strip():
        error = "Add meg az email címedet."
    else:
        existing = db.execute(
            select(User).where(User.email == email.lower().strip())
        ).scalar_one_or_none()
        if existing is not None:
            error = "Már van fiók ezzel az email-lel."

    if error:
        return templates.TemplateResponse(
            request,
            "auth/invite_redeem.html",
            {
                "invite": invite,
                "error": error,
                "name": name,
                "email": email,
                "active_flags": [f for f in ROLE_FLAGS if getattr(invite, f)],
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = User(
        name=name.strip(),
        email=email.lower().strip(),
        password_hash=hash_password(password),
        is_intake=invite.is_intake,
        is_designer=invite.is_designer,
        is_workshop=invite.is_workshop,
        is_quote_handler=invite.is_quote_handler,
        is_orderer=invite.is_orderer,
        is_admin=invite.is_admin,
        active=True,
        created_by_id=invite.created_by_id,
    )
    db.add(user)
    db.flush()

    invite.used_at = utcnow()
    invite.used_by_user_id = user.id

    raw_token = create_session(
        db,
        user,
        user_agent=request.headers.get("user-agent"),
        ip=(request.client.host if request.client else None),
    )
    db.commit()

    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, raw_token)
    return response


def _load_invite(db: Session, token: str) -> Invite | None:
    invite = db.execute(select(Invite).where(Invite.token == token)).scalar_one_or_none()
    if invite is None or invite.used_at is not None or invite.expires_at <= utcnow():
        return None
    return invite


# Az invite_submit-hoz kell — referenciát adunk a `current_session` dependency-nek
# hogy az import-graph konzisztens maradjon.
_ = UserSession
_ = current_session
