"""Globális admin route-ok: userek és meghívók kezelése.

Csak `is_admin` flag-gel rendelkező userek férhetnek hozzá. Modul-szintű
admin (kategóriák, tételek) az adott modul saját `routes/admin.py`-jában.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
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
        admin_count = db.execute(
            select(func.count())
            .select_from(User)
            .where(User.is_admin.is_(True), User.active.is_(True))
        ).scalar() or 0
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


# ───────────────────────── email accounts ─────────────────────────


def _email_accounts_ctx(
    request: FastAPIRequest,
    user: User,
    db: Session,
    *,
    test_account_id: int | None = None,
    test_ok: bool = False,
    test_result: str | None = None,
) -> dict:
    """Közös context az email-fiókok admin oldalához."""
    from app.modules.jobs.email_models import EmailAccount

    accounts = db.execute(select(EmailAccount).order_by(EmailAccount.id)).scalars().all()
    all_users = db.execute(select(User).where(User.active.is_(True)).order_by(User.name)).scalars().all()
    return {
        "user": user,
        "title": "Email fiókok",
        "topbar_title": "Email fiókok",
        "accounts": accounts,
        "all_users": all_users,
        "test_account_id": test_account_id,
        "test_ok": test_ok,
        "test_result": test_result,
        **sidebar_context(db, user, active_key="admin_email_accounts"),
    }


@router.get("/email-accounts", response_class=HTMLResponse)
def email_accounts_list(
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/email_accounts.html",
        _email_accounts_ctx(request, user, db),
    )


@router.post("/email-accounts/new")
def email_accounts_new(
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    label: str = Form(...),
    email_address: str = Form(...),
    imap_host: str = Form(...),
    imap_port: int = Form(993),
    imap_user: str = Form(...),
    imap_password: str = Form(...),
    imap_use_ssl: str | None = Form(None),
    smtp_host: str = Form(""),
    smtp_port: int = Form(587),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    smtp_use_tls: str | None = Form(None),
    viewer_ids: list[str] = Form([]),
) -> Response:
    from app.modules.jobs.email_crypto import encrypt_password
    from app.modules.jobs.email_models import EmailAccount

    account = EmailAccount(
        label=label.strip(),
        email_address=email_address.strip().lower(),
        imap_host=imap_host.strip(),
        imap_port=imap_port,
        imap_user=imap_user.strip(),
        imap_password_encrypted=encrypt_password(imap_password),
        imap_use_ssl=imap_use_ssl == "on",
        smtp_host=smtp_host.strip() or None,
        smtp_port=smtp_port,
        smtp_user=smtp_user.strip() or None,
        smtp_password_encrypted=encrypt_password(smtp_password) if smtp_password else None,
        smtp_use_tls=smtp_use_tls == "on",
        active=True,
    )
    db.add(account)
    db.flush()

    # Viewer user-ek hozzárendelése
    _set_viewers(db, account, viewer_ids)
    db.commit()
    return RedirectResponse(url="/admin/email-accounts", status_code=303)


@router.post("/email-accounts/{account_id}/update")
def email_accounts_update(
    account_id: int,
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    label: str = Form(...),
    email_address: str = Form(...),
    imap_host: str = Form(...),
    imap_port: int = Form(993),
    imap_user: str = Form(...),
    imap_password: str = Form(""),
    active: str | None = Form(None),
    imap_use_ssl: str | None = Form(None),
    smtp_host: str = Form(""),
    smtp_port: int = Form(587),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    smtp_use_tls: str | None = Form(None),
    viewer_ids: list[str] = Form([]),
) -> Response:
    from app.modules.jobs.email_crypto import encrypt_password
    from app.modules.jobs.email_models import EmailAccount

    account = db.get(EmailAccount, account_id)
    if account is None:
        raise HTTPException(404, "Email fiók nem található.")

    account.label = label.strip()
    account.email_address = email_address.strip().lower()
    account.imap_host = imap_host.strip()
    account.imap_port = imap_port
    account.imap_user = imap_user.strip()
    account.imap_use_ssl = imap_use_ssl == "on"
    account.active = active == "on"

    account.smtp_host = smtp_host.strip() or None
    account.smtp_port = smtp_port
    account.smtp_user = smtp_user.strip() or None
    account.smtp_use_tls = smtp_use_tls == "on"

    if imap_password:
        account.imap_password_encrypted = encrypt_password(imap_password)

    if smtp_password:
        account.smtp_password_encrypted = encrypt_password(smtp_password)

    _set_viewers(db, account, viewer_ids)
    db.commit()
    return RedirectResponse(url="/admin/email-accounts", status_code=303)


@router.post("/email-accounts/{account_id}/delete")
def email_accounts_delete(
    account_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    """Email fiók törlése — CASCADE törli a viewer-eket és az emaileket is."""
    from app.modules.jobs.email_models import EmailAccount

    account = db.get(EmailAccount, account_id)
    if account is None:
        raise HTTPException(404, "Email fiók nem található.")
    db.delete(account)
    db.commit()
    return RedirectResponse(url="/admin/email-accounts", status_code=303)


@router.post("/email-accounts/{account_id}/test")
def email_accounts_test(
    account_id: int,
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """IMAP kapcsolat tesztelése — bejelentkezik és kilép."""
    from app.modules.jobs.email_crypto import decrypt_password
    from app.modules.jobs.email_models import EmailAccount

    account = db.get(EmailAccount, account_id)
    if account is None:
        raise HTTPException(404, "Email fiók nem található.")

    try:
        password = decrypt_password(account.imap_password_encrypted)
        from imap_tools import MailBox

        with MailBox(account.imap_host, account.imap_port).login(
            account.imap_user, password
        ) as mb:
            folder_count = len(mb.folder.list())
            test_result = f"✓ Sikeres! {folder_count} mappa elérhető."
            test_ok = True
    except Exception as exc:
        test_result = f"✗ Hiba: {exc}"
        test_ok = False

    return templates.TemplateResponse(
        request,
        "admin/email_accounts.html",
        _email_accounts_ctx(
            request, user, db,
            test_account_id=account_id, test_ok=test_ok, test_result=test_result,
        ),
    )


# ───────────────────────── helpers ─────────────────────────


def _set_viewers(db: Session, account, viewer_ids: list[str]) -> None:
    """Email fiók viewer user-ek beállítása a checkbox-listából."""
    uid_ints = [int(v) for v in viewer_ids if v.strip().isdigit()]
    if uid_ints:
        users = db.execute(select(User).where(User.id.in_(uid_ints))).scalars().all()
        account.viewers = list(users)
    else:
        account.viewers = []


def _base_url(request: FastAPIRequest) -> str:
    """Az invite-link teljes URL-éhez a request-ből nyert host."""
    return f"{request.url.scheme}://{request.url.netloc}"


# ───────────────────────── quarantine (vírus-szkennelés) ─────────────────────────


@router.get("/quarantine", response_class=HTMLResponse)
def quarantine_list(
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Csatolmány-szkennelési státusz: fertőzött, hibás, várakozó, tiszta.

    A fertőzött fájlokat a vírusszkenner a karantén mappába mozgatja
    (uploads/quarantine/), nem a default helyén marad. Az admin innen
    láthatja, és vagy újraszkenneli (rescan) vagy törli a fájlt.
    """
    from app.modules.jobs.email_models import EmailAttachment, IncomingEmail, ScanStatus

    # Csoportos darabszámok minden státuszhoz
    counts_q = (
        db.execute(
            select(EmailAttachment.scan_status, func.count())
            .group_by(EmailAttachment.scan_status)
        )
        .all()
    )
    counts: dict[str, int] = {s.value: 0 for s in ScanStatus}
    for status_val, n in counts_q:
        counts[str(status_val)] = n

    # A "káros" listához joinold az emaillel — feladó, tárgy, dátum a UI-on
    bad_statuses = [ScanStatus.INFECTED, ScanStatus.ERROR, ScanStatus.PENDING]
    rows = (
        db.execute(
            select(EmailAttachment, IncomingEmail)
            .join(IncomingEmail, EmailAttachment.email_id == IncomingEmail.id)
            .where(EmailAttachment.scan_status.in_([s.value for s in bad_statuses]))
            .order_by(
                # infected legfelül, aztán error, aztán pending
                EmailAttachment.scan_status,
                IncomingEmail.received_at.desc(),
            )
        ).all()
    )

    # Csoportosítva, hogy a template könnyen rajzolja
    grouped: dict[str, list] = {s.value: [] for s in bad_statuses}
    for att, em in rows:
        grouped[str(att.scan_status)].append((att, em))

    return templates.TemplateResponse(
        request,
        "admin/quarantine.html",
        {
            "user": user,
            "title": "Karantén",
            "topbar_title": "Karantén",
            "topbar_subtitle": "vírus-szkennelt csatolmányok",
            "counts": counts,
            "grouped": grouped,
            "total": sum(counts.values()),
            **sidebar_context(db, user, active_key="admin_quarantine"),
        },
    )


@router.post("/quarantine/{attachment_id}/rescan")
def quarantine_rescan(
    attachment_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    """Egy csatolmány újraszkennelése (pl. ha a ClamAV daemon korábban
    nem volt elérhető, és most már igen)."""
    from app.modules.jobs.email_models import EmailAttachment
    from app.modules.jobs.virus_scanner import scan_attachment
    from app.shared.config import settings
    from pathlib import Path

    att = db.get(EmailAttachment, attachment_id)
    if att is None:
        raise HTTPException(404, "Csatolmány nem található.")

    old_status = att.scan_status
    new_status = scan_attachment(att, Path(settings.upload_dir))
    db.add(
        AuditLog(
            entity_type=AuditEntityType.EMAIL,
            entity_id=att.email_id,
            action="rescan_attachment",
            old_value=str(old_status),
            new_value=f"{new_status} ({att.filename})",
            user_id=user.id,
        )
    )
    db.commit()
    return RedirectResponse(url="/admin/quarantine", status_code=303)


@router.post("/quarantine/{attachment_id}/delete")
def quarantine_delete(
    attachment_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    """Egy fertőzött vagy hibás csatolmány végleges törlése (fájl + DB rekord).

    Csak `infected` vagy `error` státuszra engedélyezett — a `pending`
    legyen először rescan-elve, és a `clean` ne kerüljön ide soha.
    """
    from app.modules.jobs.email_models import EmailAttachment, ScanStatus
    from app.shared.config import settings
    from pathlib import Path

    att = db.get(EmailAttachment, attachment_id)
    if att is None:
        raise HTTPException(404, "Csatolmány nem található.")
    if att.scan_status not in (ScanStatus.INFECTED, ScanStatus.ERROR):
        raise HTTPException(
            409, f"Csak fertőzött vagy hibás csatolmányt törölhetsz (jelenlegi: {att.scan_status})."
        )

    # Fájl törlés a storage-ról (lehet a karantén mappában)
    fpath = Path(settings.upload_dir) / att.storage_path
    file_existed = fpath.exists()
    if file_existed:
        try:
            fpath.unlink()
        except OSError:
            pass  # ha nem sikerül, a DB rekordot akkor is töröljük

    db.add(
        AuditLog(
            entity_type=AuditEntityType.EMAIL,
            entity_id=att.email_id,
            action="delete_attachment",
            old_value=f"{att.scan_status} ({att.filename})",
            new_value=att.scan_result or "",
            user_id=user.id,
        )
    )
    db.delete(att)
    db.commit()
    return RedirectResponse(url="/admin/quarantine", status_code=303)


# A `current_user` itt nem direktben hivatkozott, de az import-graph
# transparenciájáért bent van.
_ = current_user
