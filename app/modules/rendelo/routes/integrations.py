"""Admin → Integrációk → Malfini B2B credential & stock-szinkron management.

Az admin UI:
  - GET  /admin/integrations/malfini       → status + form
  - POST /admin/integrations/malfini       → credential save
  - POST /admin/integrations/malfini/test  → login-teszt a tárolt credentiallel
  - POST /admin/integrations/malfini/refresh → kézi stock-szinkron most

A jelszó a `system_settings` táblában encrypted-en él (Fernet, SECRET_KEY-ből
származtatott kulcs — az `app.modules.jobs.email_crypto` reuses-szal). Az
admin UI csak a username-et és a base-URL-t mutatja plain szövegként; a
password mezőt placeholder-rel jelzi (van/nincs), és csak akkor írunk újra
ha az admin új értéket gépel be.
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.modules.rendelo import malfini_settings as cfg
from app.modules.rendelo.malfini_b2b import (
    MalfiniB2BError,
    fetch_availabilities_raw,
    login,
)
from app.modules.rendelo.malfini_settings import DEFAULT_MALFINI_BASE_URL, MalfiniKeys
from app.modules.rendelo.malfini_stock import (
    get_credentials,
    refresh_all_stocks,
    test_login,
)
from app.shared.db import get_db
from app.shared.dependencies import require_admin
from app.shared.models import User
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/admin/integrations", tags=["admin", "integrations"])


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/malfini")
def malfini_get(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Form + status oldal a Malfini B2B integrációhoz."""
    username = cfg.get(db, MalfiniKeys.USERNAME, default="")
    base_url = cfg.get(db, MalfiniKeys.BASE_URL, default="") or DEFAULT_MALFINI_BASE_URL
    has_password = cfg.has_value(db, MalfiniKeys.PASSWORD)

    last_login_ok_at = cfg.get(db, MalfiniKeys.LAST_LOGIN_OK_AT, default="")
    last_login_error = cfg.get(db, MalfiniKeys.LAST_LOGIN_ERROR, default="")
    last_refresh_at = cfg.get(db, MalfiniKeys.LAST_REFRESH_AT, default="")
    last_refresh_status = cfg.get(db, MalfiniKeys.LAST_REFRESH_STATUS, default="")

    return templates.TemplateResponse(
        request,
        "rendelo_admin/integrations_malfini.html",
        {
            **sidebar_context(db, user, active_key="admin_integrations_malfini"),
            "title": "Integráció — Malfini",
            "topbar_title": "Integráció — Malfini",
            "topbar_subtitle": "Rendelő modul · B2B stock-szinkron",
            "user": user,
            "username": username,
            "base_url": base_url,
            "default_base_url": DEFAULT_MALFINI_BASE_URL,
            "has_password": has_password,
            "last_login_ok_at": last_login_ok_at,
            "last_login_error": last_login_error,
            "last_refresh_at": last_refresh_at,
            "last_refresh_status": last_refresh_status,
            "flash_msg": msg,
            "flash_err": err,
        },
    )


@router.post("/malfini")
def malfini_save(
    username: str = Form(""),
    password: str = Form(""),
    base_url: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Credential mentés. Üres password = ne változtass a tároltn."""
    username = username.strip()
    base_url = base_url.strip()

    cfg.set_(db, MalfiniKeys.USERNAME, username, user_id=user.id)
    if base_url and base_url != DEFAULT_MALFINI_BASE_URL:
        cfg.set_(db, MalfiniKeys.BASE_URL, base_url, user_id=user.id)
    else:
        # Default → ne tárolj felesleges rekordot, törölhetjük
        cfg.delete(db, MalfiniKeys.BASE_URL)

    if password:
        cfg.set_(db, MalfiniKeys.PASSWORD, password, user_id=user.id)
    db.commit()

    return _redirect("/admin/integrations/malfini?msg=Mentve")


@router.post("/malfini/test")
def malfini_test(
    user: User = Depends(require_admin),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    """Login-teszt — a tárolt credentialt használja, eredmény flash."""
    ok, message = test_login(db)
    key = "msg" if ok else "err"
    return _redirect(f"/admin/integrations/malfini?{key}={urllib.parse.quote(message)}")


@router.post("/malfini/refresh")
def malfini_refresh(
    user: User = Depends(require_admin),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    """Kézi stock-szinkron most — UI gomb."""
    result = refresh_all_stocks(db)
    key = "msg" if result.ok else "err"
    return _redirect(f"/admin/integrations/malfini?{key}={urllib.parse.quote(result.message)}")


@router.post("/malfini/debug")
def malfini_debug(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Diagnosztikai: behív login + GET /product/availabilities, és visszaadja
    a raw választ az UI-on. A parser-finomításhoz kell, ha az API formátuma
    nem stimmel."""
    username, password, base_url = get_credentials(db)
    if not username or not password:
        return _redirect(
            "/admin/integrations/malfini?err=" + urllib.parse.quote("Hiányzik a credential.")
        )

    try:
        login_result = login(username, password, base_url=base_url)
        status_code, body_sample = fetch_availabilities_raw(login_result.token, base_url=base_url)
    except MalfiniB2BError as e:
        return _redirect("/admin/integrations/malfini?err=" + urllib.parse.quote(f"API hiba: {e}"))

    return templates.TemplateResponse(
        request,
        "rendelo_admin/integrations_malfini_debug.html",
        {
            **sidebar_context(db, user, active_key="admin_integrations_malfini"),
            "title": "Malfini debug",
            "topbar_title": "Malfini debug",
            "topbar_subtitle": "Raw B2B API válasz",
            "user": user,
            "status_code": status_code,
            "body_sample": body_sample,
            "body_length": len(body_sample),
            "base_url": base_url,
        },
    )


@router.post("/malfini/clear")
def malfini_clear(
    user: User = Depends(require_admin),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    """Credential törlés (pl. ha másik B2B-fiókra váltunk)."""
    cfg.delete(db, MalfiniKeys.USERNAME)
    cfg.delete(db, MalfiniKeys.PASSWORD)
    cfg.delete(db, MalfiniKeys.BASE_URL)
    cfg.delete(db, MalfiniKeys.LAST_LOGIN_OK_AT)
    cfg.delete(db, MalfiniKeys.LAST_LOGIN_ERROR)
    db.commit()
    return _redirect("/admin/integrations/malfini?msg=T%C3%B6r%C3%B6lve")
