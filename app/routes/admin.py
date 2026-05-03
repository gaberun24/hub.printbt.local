"""Globális admin route-ok: userek és meghívók kezelése.

Csak `is_admin` flag-gel rendelkező userek férhetnek hozzá. Modul-szintű
admin (kategóriák, tételek) az adott modul saját `routes/admin.py`-jában.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.db import get_db
from app.shared.dependencies import current_user, require_admin
from app.shared.models import ROLE_FLAGS, AuditEntityType, AuditLog, Invite, User, utcnow
from app.shared.security import generate_token
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/admin", tags=["admin"])


# ───────────────────────── helpers ─────────────────────────


def _audit_user(
    db: Session, admin_id: int, user_id: int, action: str, *, old: str = "", new: str = ""
) -> None:
    db.add(
        AuditLog(
            entity_type=AuditEntityType.USER,
            entity_id=user_id,
            action=action,
            old_value=old,
            new_value=new,
            user_id=admin_id,
        )
    )


# ───────────────────────── users ─────────────────────────


@router.get("/users", response_class=HTMLResponse)
def users_list(
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        {
            "user": user,
            "title": "Userek",
            "topbar_title": "Userek",
            "topbar_subtitle": "szerepkörök és aktív státusz",
            "users": users,
            "role_flags": ROLE_FLAGS,
            **sidebar_context(db, user, active_key="admin_users"),
        },
    )


@router.post("/users/{user_id}/update")
def users_update(
    user_id: int,
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    is_intake: str | None = Form(None),
    is_designer: str | None = Form(None),
    is_workshop: str | None = Form(None),
    is_quote_handler: str | None = Form(None),
    is_orderer: str | None = Form(None),
    is_admin: str | None = Form(None),
    active: str | None = Form(None),
) -> Response:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User nem található.")

    # Védelem: az admin saját magát ne tudja `is_admin`-ról levenni egyedüli adminként.
    new_is_admin = is_admin == "on"
    if not new_is_admin and target.id == user.id:
        admin_count = (
            db.execute(select(User).where(User.is_admin.is_(True), User.active.is_(True)))
            .all()
            .__len__()
        )
        if admin_count <= 1:
            raise HTTPException(409, "Nem veheted le magadról az utolsó admin-jogot.")

    flag_form_values = {
        "is_intake": is_intake,
        "is_designer": is_designer,
        "is_workshop": is_workshop,
        "is_quote_handler": is_quote_handler,
        "is_orderer": is_orderer,
        "is_admin": is_admin,
    }
    old_flags = {f: getattr(target, f) for f in ROLE_FLAGS}
    for flag in ROLE_FLAGS:
        setattr(target, flag, flag_form_values[flag] == "on")
    target.active = active == "on"

    new_flags = {f: getattr(target, f) for f in ROLE_FLAGS}
    if old_flags != new_flags:
        _audit_user(
            db,
            user.id,
            target.id,
            "roles_change",
            old=",".join(f for f, v in old_flags.items() if v),
            new=",".join(f for f, v in new_flags.items() if v),
        )

    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


# ───────────────────────── invites ─────────────────────────


@router.get("/invites", response_class=HTMLResponse)
def invites_list(
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    show_all: bool = False,
) -> HTMLResponse:
    stmt = select(Invite).order_by(Invite.created_at.desc())
    if not show_all:
        stmt = stmt.where(Invite.used_at.is_(None), Invite.expires_at > utcnow())
    invites = db.execute(stmt).scalars().all()
    return templates.TemplateResponse(
        request,
        "admin/invites.html",
        {
            "user": user,
            "title": "Meghívók",
            "topbar_title": "Meghívók",
            "topbar_subtitle": "felhasználói tokenek és érvényesség",
            "invites": invites,
            "show_all": show_all,
            "role_flags": ROLE_FLAGS,
            "base_url": _base_url(request),
            **sidebar_context(db, user, active_key="admin_invites"),
        },
    )


@router.post("/invites/new")
def invites_new(
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    email_hint: str | None = Form(None),
    expires_days: int = Form(7),
    is_intake: str | None = Form(None),
    is_designer: str | None = Form(None),
    is_workshop: str | None = Form(None),
    is_quote_handler: str | None = Form(None),
    is_orderer: str | None = Form(None),
    is_admin: str | None = Form(None),
) -> Response:
    flags = {
        "is_intake": is_intake == "on",
        "is_designer": is_designer == "on",
        "is_workshop": is_workshop == "on",
        "is_quote_handler": is_quote_handler == "on",
        "is_orderer": is_orderer == "on",
        "is_admin": is_admin == "on",
    }
    if not any(flags.values()):
        raise HTTPException(400, "Adj meg legalább egy szerepkört.")

    invite = Invite(
        token=generate_token(32),
        email_hint=(email_hint or "").strip() or None,
        created_by_id=user.id,
        expires_at=utcnow() + timedelta(days=max(1, min(90, expires_days))),
        **flags,
    )
    db.add(invite)
    db.commit()
    return RedirectResponse(url="/admin/invites", status_code=303)


@router.post("/invites/{invite_id}/revoke")
def invites_revoke(
    invite_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(404, "Meghívó nem található.")
    if invite.used_at is not None:
        raise HTTPException(409, "Felhasznált meghívót nem vonhatsz vissza.")
    # Lejárati időt a múltba állítjuk → a `_load_invite` (auth) ezt invalidnak látja
    invite.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    return RedirectResponse(url="/admin/invites", status_code=303)


# ───────────────────────── helpers ─────────────────────────


def _base_url(request: FastAPIRequest) -> str:
    """Az invite-link teljes URL-éhez a request-ből nyert host."""
    return f"{request.url.scheme}://{request.url.netloc}"


# A `current_user` itt nem direktben hivatkozott, de az import-graph
# transparenciájáért bent van.
_ = current_user
