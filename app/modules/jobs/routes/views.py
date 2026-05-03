"""Munkák modul page-route-jai (Fázis 2.2 — kezdő CRUD).

Most: /jobs (saját + közös pool toggle), /jobs/new (felvétel form), és
/jobs/{public_id} (minimális detail). A teljes mockup-faithful detail
+ státusz-akciók a 2.3-ban jönnek.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.modules.jobs.models import (
    IntakeChannel,
    Job,
    JobEvent,
    JobEventAction,
    JobStatus,
    JobTask,
    JobType,
    TaskStatus,
    TaskType,
)
from app.modules.jobs.public_id import generate_unique, normalize
from app.modules.jobs.services import (
    can_transition,
    mark_job_delivered,
    recompute_job_status,
)
from app.shared.config import settings
from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import (
    AuditEntityType,
    AuditLog,
    Customer,
    User,
    get_setting_int,
    utcnow,
)
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/jobs", tags=["jobs"])


# ───────────────────────── helpers ─────────────────────────


_ACTIVE_STATUSES = (
    JobStatus.FELVETT,
    JobStatus.GRAFIKAN,
    JobStatus.KESZ_LATVANY,
    JobStatus.UGYFEL_JOVAHAGYAS_VAR,
    JobStatus.MUHELYBEN,
    JobStatus.KESZ,
)


def _group_by_status(jobs: list[Job]) -> dict[str, list[Job]]:
    """A dashboard-szerű szekciókhoz csoportosítja a Job-okat státusz szerint.
    A sorrend megegyezik a state-machine sorrendjével."""
    groups: dict[str, list[Job]] = {s.value: [] for s in _ACTIVE_STATUSES}
    for j in jobs:
        groups.setdefault(str(j.status), []).append(j)
    return groups


# ───────────────────────── list ─────────────────────────


@router.get("", response_class=HTMLResponse)
def jobs_list(
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    view: str = Query("own", description="own | pool | all | deleted"),
    job_type: str | None = Query(None, description="job_type szűrés"),
) -> HTMLResponse:
    """Saját munkáim / Közös pool / Mind / Törölt (recycle bin) +
    opcionális job_type szűrés."""

    # A `deleted` view admin-only — különben 403
    is_recycle_bin = view == "deleted"
    if is_recycle_bin and not user.is_admin:
        raise HTTPException(403, "Csak admin férhet hozzá a törölt munkákhoz.")

    stmt = select(Job).options(
        selectinload(Job.customer),
        selectinload(Job.tasks),
        selectinload(Job.intake_user),
        selectinload(Job.assigned_designer),
        selectinload(Job.deleted_by),
    )

    if is_recycle_bin:
        stmt = stmt.where(Job.deleted_at.is_not(None)).order_by(Job.deleted_at.desc())
        view_label = "Törölt munkák"
        active_key = "jobs_own"
    else:
        # Default: élő rekordok (deleted_at IS NULL) és aktív státusz
        stmt = (
            stmt.where(Job.deleted_at.is_(None))
            .where(Job.status.in_(_ACTIVE_STATUSES))
            .order_by(Job.deadline.asc())
        )
        if view == "own":
            stmt = stmt.where(
                or_(Job.intake_user_id == user.id, Job.assigned_designer_id == user.id)
            )
            view_label = "Saját munkáim"
            active_key = "jobs_own"
        elif view == "pool":
            stmt = stmt.where(Job.assigned_designer_id.is_(None))
            view_label = "Közös pool"
            active_key = "jobs_pool"
        else:
            view_label = "Minden aktív munka"
            active_key = "jobs_own"

    active_job_type = None
    if job_type:
        try:
            active_job_type = JobType(job_type)
            stmt = stmt.where(Job.job_type == active_job_type)
        except ValueError:
            pass

    jobs = list(db.execute(stmt).scalars().all())
    groups = _group_by_status(jobs) if not is_recycle_bin else None

    retention_days = get_setting_int(db, "jobs.recycle_retention_days", 90)

    return templates.TemplateResponse(
        request,
        "jobs/list.html",
        {
            "user": user,
            "title": view_label,
            "topbar_title": view_label,
            "topbar_subtitle": (
                f"{retention_days} napig tároljuk a törölteket"
                if is_recycle_bin
                else f"{len(jobs)} aktív munka"
            ),
            "view": view,
            "view_label": view_label,
            "is_recycle_bin": is_recycle_bin,
            "retention_days": retention_days,
            "active_job_type": active_job_type.value if active_job_type else None,
            "job_types": list(JobType),
            "jobs": jobs,
            "groups": groups,
            **sidebar_context(db, user, active_key=active_key),
        },
    )


# ───────────────────────── new ─────────────────────────


@router.get("/new", response_class=HTMLResponse)
def jobs_new_form(
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    error: str | None = Query(None),
    customer_id: int | None = Query(None, description="prefill from /customers/.../új munka"),
) -> HTMLResponse:
    if not (user.is_admin or user.is_intake or user.is_designer):
        raise HTTPException(403, "Új munka felvételéhez intake vagy designer jog kell.")

    customers = db.execute(select(Customer).order_by(Customer.name)).scalars().all()
    prefill_customer = db.get(Customer, customer_id) if customer_id else None

    return templates.TemplateResponse(
        request,
        "jobs/new.html",
        {
            "user": user,
            "title": "Új munka",
            "topbar_title": "Új munka",
            "topbar_subtitle": "felvétel: ügyfél, határidő, taskok",
            "customers": customers,
            "prefill_customer": prefill_customer,
            "error": error,
            "job_types": list(JobType),
            "task_types": list(TaskType),
            "intake_channels": list(IntakeChannel),
            **sidebar_context(db, user, active_key="jobs_new"),
        },
    )


def _parse_deadline(raw: str) -> datetime | None:
    """`<input type="datetime-local">` `YYYY-MM-DDTHH:MM` formátumát parse-olja."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@router.post("/new")
def jobs_new_submit(
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    customer_id: int = Form(...),
    job_type: str = Form("other"),
    deadline: str = Form(...),
    intake_channel: str = Form("personal"),
    is_urgent: str | None = Form(None),
    description: str | None = Form(None),
    source_file_path: str | None = Form(None),
    price_huf: int | None = Form(None),
    pool: str | None = Form(None),
    task_type: list[str] = Form(default_factory=list),
    task_quantity: list[str] = Form(default_factory=list),
    task_instructions: list[str] = Form(default_factory=list),
) -> Response:
    if not (user.is_admin or user.is_intake or user.is_designer):
        raise HTTPException(403, "Új munka felvételéhez intake vagy designer jog kell.")

    customer = db.get(Customer, customer_id)
    if customer is None:
        return RedirectResponse(url="/jobs/new?error=Ismeretlen+%C3%BCgyf%C3%A9l", status_code=303)

    parsed_deadline = _parse_deadline(deadline)
    if parsed_deadline is None:
        return RedirectResponse(
            url="/jobs/new?error=K%C3%A9rlek+adj+meg+hat%C3%A1rid%C5%91t", status_code=303
        )

    # Task-ok parse: tisztítás, üres rows kihagyása
    cleaned_tasks: list[tuple[TaskType, int, str | None]] = []
    for raw_type, raw_qty, raw_instr in zip(
        task_type, task_quantity, task_instructions, strict=False
    ):
        rt = (raw_type or "").strip()
        if not rt:
            continue
        try:
            tt = TaskType(rt)
        except ValueError:
            continue
        try:
            qty = max(1, int((raw_qty or "1").strip() or "1"))
        except ValueError:
            qty = 1
        instr = (raw_instr or "").strip() or None
        cleaned_tasks.append((tt, qty, instr))

    if not cleaned_tasks:
        return RedirectResponse(
            url="/jobs/new?error=Adj+meg+legal%C3%A1bb+egy+taskot", status_code=303
        )

    try:
        ic = IntakeChannel(intake_channel)
    except ValueError:
        ic = IntakeChannel.PERSONAL

    try:
        jt = JobType(job_type)
    except ValueError:
        jt = JobType.OTHER

    # Pool-flag: bekapcsolt = közös pool (assigned_designer_id NULL),
    # kikapcsolt = magamhoz veszem (designer-jog kell hozzá)
    assigned_designer_id = None if pool == "on" or not user.is_designer else user.id

    job = Job(
        public_id=generate_unique(db),
        customer_id=customer.id,
        job_type=jt,
        intake_user_id=user.id,
        intake_channel=ic,
        assigned_designer_id=assigned_designer_id,
        deadline=parsed_deadline,
        is_urgent=(is_urgent == "on"),
        price_huf=price_huf if price_huf and price_huf > 0 else None,
        description=(description or "").strip() or None,
        source_file_path=(source_file_path or "").strip() or None,
        status=JobStatus.FELVETT,
    )
    db.add(job)
    db.flush()

    for tt, qty, instr in cleaned_tasks:
        db.add(
            JobTask(
                job_id=job.id,
                task_type=tt,
                quantity=qty,
                instructions=instr,
            )
        )

    _audit_job(
        db,
        user,
        job,
        "create",
        new=json.dumps(
            {
                "public_id": job.public_id,
                "customer_id": customer.id,
                "task_count": len(cleaned_tasks),
                "is_urgent": job.is_urgent,
            },
            ensure_ascii=False,
        ),
    )
    # CREATED Event a timeline-ra is
    _log_event(
        db,
        job,
        user,
        JobEventAction.CREATED,
        {"task_count": len(cleaned_tasks), "job_type": str(job.job_type)},
    )
    db.commit()

    return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)


# ───────────────────────── detail (minimal) ─────────────────────────


def _load_job_or_404(db: Session, public_id: str) -> Job:
    norm = normalize(public_id)
    if not norm:
        raise HTTPException(404, "Job nem található.")
    job = db.execute(
        select(Job)
        .options(
            selectinload(Job.customer),
            selectinload(Job.tasks).selectinload(JobTask.assigned_to),
            selectinload(Job.intake_user),
            selectinload(Job.assigned_designer),
            selectinload(Job.attachments),
            selectinload(Job.events).selectinload(JobEvent.user),
        )
        .where(Job.public_id == norm)
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "Job nem található.")
    return job


def _log_event(
    db: Session,
    job: Job,
    user: User,
    action: JobEventAction,
    payload: dict | None = None,
) -> None:
    db.add(
        JobEvent(
            job_id=job.id,
            user_id=user.id,
            action=action,
            payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
        )
    )


# ───────────────────────── workshop ─────────────────────────


@router.get("/workshop", response_class=HTMLResponse)
def jobs_workshop(
    request: FastAPIRequest,
    machine: str | None = Query(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Műhely nézet: összes nyitott task kártyaként, gép-szűrővel."""
    base_q = (
        select(JobTask)
        .join(Job, JobTask.job_id == Job.id)
        .options(
            selectinload(JobTask.job).selectinload(Job.customer),
            selectinload(JobTask.job).selectinload(Job.intake_user),
            selectinload(JobTask.assigned_to),
        )
        .where(
            JobTask.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
            Job.deleted_at.is_(None),
            Job.status.in_([
                JobStatus.MUHELYBEN,
                JobStatus.GRAFIKAN,
                JobStatus.FELVETT,
                JobStatus.KESZ_LATVANY,
                JobStatus.UGYFEL_JOVAHAGYAS_VAR,
            ]),
        )
        .order_by(Job.is_urgent.desc(), Job.deadline.asc())
    )

    all_tasks: list[JobTask] = db.execute(base_q).scalars().all()

    counts: dict[str, int] = {}
    for t in all_tasks:
        tt = str(t.task_type)
        counts[tt] = counts.get(tt, 0) + 1
    machine_counts = sorted(counts.items(), key=lambda x: -x[1])

    tasks = [t for t in all_tasks if str(t.task_type) == machine] if machine else all_tasks

    return templates.TemplateResponse(
        request,
        "jobs/workshop.html",
        {
            "user": user,
            "title": "Műhely",
            "topbar_title": "Műhely",
            "topbar_subtitle": f"{len(tasks)} feladat",
            "tasks": tasks,
            "total_count": len(all_tasks),
            "machine_counts": machine_counts,
            "active_machine": machine,
            **sidebar_context(db, user, active_key="jobs_workshop"),
        },
    )


# ───────────────────────── inbox ─────────────────────────


def _visible_account_ids(db: Session, user: User) -> list[int]:
    """A user számára látható email-fiók ID-k listája.

    Logika: egy fiók látható ha:
      - nincs hozzá viewer rendelve (közös fiók, mindenki látja), VAGY
      - a user a fiók viewer-ei között van
    """
    from app.modules.jobs.email_models import EmailAccount

    # Közös fiókok (nincs viewer hozzárendelve)
    shared_ids = (
        db.execute(
            select(EmailAccount.id).where(
                EmailAccount.active.is_(True),
                ~EmailAccount.viewers.any(),
            )
        )
        .scalars()
        .all()
    )

    # User-hez rendelt fiókok
    assigned_ids = (
        db.execute(
            select(EmailAccount.id).where(
                EmailAccount.active.is_(True),
                EmailAccount.viewers.any(User.id == user.id),
            )
        )
        .scalars()
        .all()
    )

    return list(set(shared_ids) | set(assigned_ids))



def _get_thread(db: Session, email) -> list:
    """Egy email thread-jének összes üzenete időrendben."""
    from app.modules.jobs.email_models import IncomingEmail

    thread_key = email.thread_id or email.message_id
    if not thread_key:
        return [email]

    msgs = list(
        db.execute(
            select(IncomingEmail)
            .options(selectinload(IncomingEmail.attachments))
            .where(
                or_(
                    IncomingEmail.thread_id == thread_key,
                    IncomingEmail.message_id == thread_key,
                    IncomingEmail.id == email.id,
                ),
                IncomingEmail.purged_at.is_(None),
            )
            .order_by(IncomingEmail.received_at.asc())
        )
        .scalars()
        .all()
    )
    if not msgs:
        return [email]
    seen = set()
    unique = []
    for m in msgs:
        if m.id not in seen:
            seen.add(m.id)
            unique.append(m)
    return unique


def _visible_accounts_list(db: Session, visible_account_ids: list[int]) -> list:
    """Visible email fiókok listája a compose dropdown-hoz."""
    from app.modules.jobs.email_models import EmailAccount

    if not visible_account_ids:
        return []
    return list(
        db.execute(
            select(EmailAccount).where(EmailAccount.id.in_(visible_account_ids))
        )
        .scalars()
        .all()
    )


def _inbox_search_filter(q: str):
    """ILIKE keresés feladó, cím, tárgy és body-ban."""
    from app.modules.jobs.email_models import IncomingEmail

    pattern = f"%{q}%"
    return or_(
        IncomingEmail.from_name.ilike(pattern),
        IncomingEmail.from_address.ilike(pattern),
        IncomingEmail.subject.ilike(pattern),
        IncomingEmail.body_text.ilike(pattern),
    )


@router.get("/inbox", response_class=HTMLResponse)
def jobs_inbox(
    request: FastAPIRequest,
    tab: str = Query("work"),
    q: str = Query(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Bejövő posta — 5 tabes inbox nézet, keresővel."""
    from app.modules.jobs.email_models import EmailCategory, IncomingEmail

    valid_tabs = {c.value for c in EmailCategory}
    active_tab = tab if tab in valid_tabs else "work"
    search_q = q.strip()

    visible_account_ids = _visible_account_ids(db, user)

    base = select(IncomingEmail).where(
        IncomingEmail.purged_at.is_(None),
        IncomingEmail.account_id.in_(visible_account_ids) if visible_account_ids else True,
    )

    if search_q:
        base = base.where(_inbox_search_filter(search_q))

    all_emails = (
        db.execute(base.order_by(IncomingEmail.received_at.desc()))
        .scalars()
        .all()
    )

    counts: dict[str, int] = {c.value: 0 for c in EmailCategory}
    for em in all_emails:
        cat = str(em.effective_category) if em.effective_category else "other"
        counts[cat] = counts.get(cat, 0) + 1

    # Ha keresünk, ne szűrjünk tabra — mutassuk az összeset
    if search_q:
        filtered = all_emails
        active_tab = ""
    else:
        filtered = [
            em
            for em in all_emails
            if (str(em.effective_category) if em.effective_category else "other") == active_tab
        ]


    return templates.TemplateResponse(
        request,
        "jobs/inbox.html",
        {
            "user": user,
            "title": "Bejövő posta",
            "topbar_title": "Bejövő posta",
            "topbar_subtitle": f"{len(filtered)} email",
            "emails": filtered,
            "selected": filtered[0] if filtered else None,
            "selected_id": filtered[0].id if filtered else None,
            "thread": _get_thread(db, filtered[0]) if filtered else [],
            "total_count": len(all_emails),
            "counts": counts,
            "active_tab": active_tab,
            "search_q": search_q,
            "smtp_configured": bool(settings.smtp_host),
            "visible_accounts": _visible_accounts_list(db, visible_account_ids),
            **sidebar_context(db, user, active_key="jobs_inbox"),
        },
    )


@router.get("/inbox/{email_id}", response_class=HTMLResponse)
def jobs_inbox_detail(
    email_id: int,
    request: FastAPIRequest,
    tab: str = Query("work"),
    q: str = Query(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Inbox email részletek — bal oldali lista + jobb oldali detail."""
    from app.modules.jobs.email_models import (
        EmailCategory,
        IncomingEmail,
    )

    valid_tabs = {c.value for c in EmailCategory}
    active_tab = tab if tab in valid_tabs else "work"
    search_q = q.strip()

    visible_account_ids = _visible_account_ids(db, user)

    selected = db.execute(
        select(IncomingEmail)
        .options(selectinload(IncomingEmail.attachments))
        .where(IncomingEmail.id == email_id)
    ).scalar_one_or_none()

    if selected is None:
        raise HTTPException(404, "Email nem található.")

    if visible_account_ids and selected.account_id not in visible_account_ids:
        raise HTTPException(403, "Nincs hozzáférésed ehhez az emailhez.")

    if not selected.is_read:
        selected.is_read = True
        db.commit()

    thread = _get_thread(db, selected)

    base = select(IncomingEmail).where(
        IncomingEmail.purged_at.is_(None),
        IncomingEmail.account_id.in_(visible_account_ids) if visible_account_ids else True,
    )

    if search_q:
        base = base.where(_inbox_search_filter(search_q))

    all_emails = (
        db.execute(base.order_by(IncomingEmail.received_at.desc()))
        .scalars()
        .all()
    )

    counts: dict[str, int] = {c.value: 0 for c in EmailCategory}
    for em in all_emails:
        cat = str(em.effective_category) if em.effective_category else "other"
        counts[cat] = counts.get(cat, 0) + 1

    if search_q:
        filtered = all_emails
        active_tab = ""
    else:
        filtered = [
            em
            for em in all_emails
            if (str(em.effective_category) if em.effective_category else "other") == active_tab
        ]


    return templates.TemplateResponse(
        request,
        "jobs/inbox.html",
        {
            "user": user,
            "title": "Bejövő posta",
            "topbar_title": "Bejövő posta",
            "topbar_subtitle": selected.subject or "(nincs tárgy)",
            "emails": filtered,
            "selected": selected,
            "selected_id": selected.id,
            "thread": thread,
            "total_count": len(all_emails),
            "counts": counts,
            "active_tab": active_tab,
            "search_q": search_q,
            "smtp_configured": bool(settings.smtp_host),
            "visible_accounts": _visible_accounts_list(db, visible_account_ids),
            **sidebar_context(db, user, active_key="jobs_inbox"),
        },
    )


async def _read_upload_files(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    """Upload fájlok beolvasása (filename, bytes) tuple-ökbe."""
    result = []
    for f in files:
        if f.filename and f.size and f.size > 0:
            data = await f.read()
            result.append((f.filename, data))
    return result


@router.post("/inbox/{email_id}/reply")
async def inbox_reply(
    email_id: int,
    to_address: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    attachments: list[UploadFile] = File(default=[]),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Válasz küldése egy bejövő emailre."""
    from app.modules.jobs.email_models import IncomingEmail
    from app.modules.jobs.email_sender import send_email

    email = db.execute(
        select(IncomingEmail).where(IncomingEmail.id == email_id)
    ).scalar_one_or_none()
    if email is None:
        raise HTTPException(404, "Email nem található.")

    visible_ids = _visible_account_ids(db, user)
    if visible_ids and email.account_id not in visible_ids:
        raise HTTPException(403, "Nincs hozzáférésed ehhez az emailhez.")

    account = email.account
    file_list = await _read_upload_files(attachments)

    try:
        msg_id = send_email(
            account.label,
            account.email_address,
            to_address.strip(),
            subject.strip(),
            body,
            in_reply_to=email.message_id,
            references=email.message_id,
            attachments=file_list,
        )
    except Exception as exc:
        raise HTTPException(500, f"Email küldés sikertelen: {exc}") from exc

    _save_sent_email(
        db, account, user, to_address.strip(), subject.strip(), body, msg_id,
        in_reply_to=email.message_id, thread_id=email.thread_id or email.message_id,
    )

    tab = str(email.effective_category or "work")
    return RedirectResponse(
        url=f"/jobs/inbox/{email_id}?tab={tab}", status_code=303
    )


@router.post("/inbox/compose")
async def inbox_compose(
    to_address: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    account_id: int = Form(...),
    attachments: list[UploadFile] = File(default=[]),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Új email küldése egy választott fiókból."""
    from app.modules.jobs.email_models import EmailAccount
    from app.modules.jobs.email_sender import send_email

    account = db.get(EmailAccount, account_id)
    if account is None:
        raise HTTPException(404, "Email fiók nem található.")

    visible_ids = _visible_account_ids(db, user)
    if visible_ids and account.id not in visible_ids:
        raise HTTPException(403, "Nincs hozzáférésed ehhez a fiókhoz.")

    file_list = await _read_upload_files(attachments)

    try:
        msg_id = send_email(
            account.label,
            account.email_address,
            to_address.strip(),
            subject.strip(),
            body,
            attachments=file_list,
        )
    except Exception as exc:
        raise HTTPException(500, f"Email küldés sikertelen: {exc}") from exc

    _save_sent_email(
        db, account, user, to_address.strip(), subject.strip(), body, msg_id,
    )

    return RedirectResponse(url="/jobs/inbox", status_code=303)


def _save_sent_email(
    db: Session,
    account,
    user: User,
    to_address: str,
    subject: str,
    body: str,
    message_id: str,
    *,
    in_reply_to: str | None = None,
    thread_id: str | None = None,
) -> None:
    """Elküldött email mentése a DB-be a beszélgetés-szál követéséhez."""
    from app.modules.jobs.email_models import IncomingEmail

    sent = IncomingEmail(
        account_id=account.id,
        message_id=message_id,
        from_address=account.email_address,
        from_name=account.label,
        to_address=to_address,
        subject=subject,
        body_text=body,
        received_at=utcnow(),
        in_reply_to=in_reply_to,
        thread_id=thread_id or message_id,
        is_outgoing=True,
        sent_by_user_id=user.id,
        is_read=True,
    )
    db.add(sent)
    db.commit()


@router.post("/inbox/{email_id}/recategorize")
def inbox_recategorize(
    email_id: int,
    category: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Email manuális átsorolása másik kategóriába."""
    from app.modules.jobs.email_models import EmailCategory, IncomingEmail

    email = db.get(IncomingEmail, email_id)
    if email is None:
        raise HTTPException(404, "Email nem található.")

    # Jogosultság-ellenőrzés
    visible_account_ids = _visible_account_ids(db, user)
    if visible_account_ids and email.account_id not in visible_account_ids:
        raise HTTPException(403, "Nincs hozzáférésed ehhez az emailhez.")

    try:
        new_cat = EmailCategory(category)
    except ValueError:
        raise HTTPException(400, f"Érvénytelen kategória: {category}")  # noqa: B904

    old_cat = str(email.effective_category or "—")
    email.manual_category = new_cat
    email.manual_category_by_id = user.id
    db.add(
        AuditLog(
            entity_type=AuditEntityType.EMAIL,
            entity_id=email.id,
            action="recategorize",
            old_value=old_cat,
            new_value=str(new_cat),
            user_id=user.id,
        )
    )
    db.commit()
    return RedirectResponse(
        url=f"/jobs/inbox/{email_id}?tab={category}", status_code=303
    )


@router.get("/{public_id}", response_class=HTMLResponse)
def jobs_detail(
    public_id: str,
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Teljes Job-detail: hero + részletek + taskok + akciók + komment-stream."""
    job = _load_job_or_404(db, public_id)

    # Designer-reassignment dropdown opciói
    designers = (
        db.execute(
            select(User)
            .where(User.is_designer.is_(True), User.active.is_(True))
            .order_by(User.name)
        )
        .scalars()
        .all()
    )

    # Engedélyezett state-átmenetek a jelenlegi státuszból
    next_states = sorted(
        s.value
        for s in JobStatus
        if can_transition(job.status, s)
        # az automatikus `kesz` és a terminal `atadva` nem manuális akcióra megy
        and s not in (JobStatus.KESZ,)
    )

    return templates.TemplateResponse(
        request,
        "jobs/detail.html",
        {
            "user": user,
            "title": f"Munka {public_id}",
            "topbar_title": f"{job.public_id[:3]}-{job.public_id[3:]}",
            "topbar_subtitle": job.customer.name,
            "job": job,
            "designers": designers,
            "next_states": next_states,
            "retention_days": get_setting_int(db, "jobs.recycle_retention_days", 90),
            **sidebar_context(db, user, active_key="jobs_own"),
        },
    )


# ───────────────────────── task actions ─────────────────────────


def _get_task(job: Job, task_id: int) -> JobTask:
    for t in job.tasks:
        if t.id == task_id:
            return t
    raise HTTPException(404, "Task nem található ehhez a Job-hoz.")


def _audit_job(
    db: Session, user: User, job: Job, action: str, *, old: str = "", new: str = ""
) -> None:
    db.add(
        AuditLog(
            entity_type=AuditEntityType.JOB,
            entity_id=job.id,
            action=action,
            old_value=old,
            new_value=new,
            user_id=user.id,
        )
    )


@router.post("/{public_id}/tasks/{task_id}/claim")
def task_claim(
    public_id: str,
    task_id: int,
    next: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _load_job_or_404(db, public_id)
    task = _get_task(job, task_id)
    task.assigned_to_user_id = user.id
    if task.status == TaskStatus.PENDING:
        task.status = TaskStatus.IN_PROGRESS
    _log_event(
        db,
        job,
        user,
        JobEventAction.TASK_CLAIMED,
        {"task_id": task.id, "task_type": str(task.task_type)},
    )
    new_status = recompute_job_status(job)
    if new_status:
        _log_event(
            db,
            job,
            user,
            JobEventAction.STATUS_CHANGE,
            {"from": "felvett", "to": str(new_status), "auto": True},
        )
        _audit_job(db, user, job, "status_change", old="felvett", new=str(new_status))
    db.commit()
    redirect_url = next if next and next.startswith("/jobs/workshop") else f"/jobs/{job.public_id}"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/{public_id}/tasks/{task_id}/done")
def task_done(
    public_id: str,
    task_id: int,
    next: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _load_job_or_404(db, public_id)
    task = _get_task(job, task_id)
    task.status = TaskStatus.DONE
    if task.completed_at is None:
        task.completed_at = utcnow()
    if task.assigned_to_user_id is None:
        task.assigned_to_user_id = user.id
    _log_event(
        db,
        job,
        user,
        JobEventAction.TASK_DONE,
        {"task_id": task.id, "task_type": str(task.task_type)},
    )
    old_status = str(job.status)
    new_status = recompute_job_status(job)
    if new_status:
        _log_event(
            db,
            job,
            user,
            JobEventAction.STATUS_CHANGE,
            {"from": old_status, "to": str(new_status), "auto": True},
        )
        _audit_job(db, user, job, "status_change", old=old_status, new=str(new_status))
    db.commit()
    redirect_url = next if next and next.startswith("/jobs/workshop") else f"/jobs/{job.public_id}"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/{public_id}/tasks/{task_id}/release")
def task_release(
    public_id: str,
    task_id: int,
    next: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _load_job_or_404(db, public_id)
    task = _get_task(job, task_id)
    task.assigned_to_user_id = None
    if task.status == TaskStatus.IN_PROGRESS:
        task.status = TaskStatus.PENDING
    _log_event(
        db,
        job,
        user,
        JobEventAction.TASK_RELEASED,
        {"task_id": task.id, "task_type": str(task.task_type)},
    )
    db.commit()
    redirect_url = next if next and next.startswith("/jobs/workshop") else f"/jobs/{job.public_id}"
    return RedirectResponse(url=redirect_url, status_code=303)


# ───────────────────────── job state ─────────────────────────


@router.post("/{public_id}/state")
def jobs_change_state(
    public_id: str,
    next_status: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _load_job_or_404(db, public_id)
    try:
        target = JobStatus(next_status)
    except ValueError:
        raise HTTPException(400, f"Ismeretlen státusz: {next_status}") from None

    if not can_transition(job.status, target):
        raise HTTPException(409, f"Tiltott átmenet: {job.status} → {target}")

    old_status = str(job.status)
    if target == JobStatus.ATADVA:
        mark_job_delivered(job)
    else:
        job.status = target

    _log_event(
        db,
        job,
        user,
        JobEventAction.STATUS_CHANGE,
        {"from": old_status, "to": str(target)},
    )
    _audit_job(db, user, job, "status_change", old=old_status, new=str(target))
    db.commit()
    return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)


# ───────────────────────── designer reassignment ─────────────────────────


@router.post("/{public_id}/assign-designer")
def jobs_assign_designer(
    public_id: str,
    designer_id: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _load_job_or_404(db, public_id)
    old = job.assigned_designer_id
    new_id: int | None
    if not designer_id or designer_id == "pool":
        new_id = None
    else:
        try:
            new_id = int(designer_id)
        except ValueError:
            raise HTTPException(400, "Hibás designer-azonosító.") from None
        if not db.execute(
            select(User).where(User.id == new_id, User.is_designer.is_(True))
        ).scalar_one_or_none():
            raise HTTPException(400, "Csak aktív designer rendelhető hozzá.")

    if old == new_id:
        return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)

    job.assigned_designer_id = new_id
    _log_event(
        db,
        job,
        user,
        JobEventAction.DESIGNER_ASSIGNED,
        {"from_id": old, "to_id": new_id},
    )
    _audit_job(
        db, user, job, "designer_assigned", old=str(old or "pool"), new=str(new_id or "pool")
    )
    db.commit()
    return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)


# ───────────────────────── comment ─────────────────────────


@router.post("/{public_id}/comment")
def jobs_comment(
    public_id: str,
    body: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _load_job_or_404(db, public_id)
    body = (body or "").strip()
    if not body:
        return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)
    _log_event(db, job, user, JobEventAction.COMMENTED, {"body": body})
    db.commit()
    return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)


# ───────────────────────── soft delete + restore ─────────────────────────


def _can_delete_job(user: User, job: Job) -> bool:
    """Ki törölhet egy Job-ot:
    - admin (mindig)
    - intake user önmaga által felvett Job-ot, ha még friss (24 órán belül)
    """
    if user.is_admin:
        return True
    if user.is_intake and job.intake_user_id == user.id:
        age = utcnow() - job.created_at
        if age.total_seconds() <= 24 * 3600:
            return True
    return False


@router.post("/{public_id}/delete")
def jobs_delete(
    public_id: str,
    confirm: str = Form(...),
    reason: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _load_job_or_404(db, public_id)

    if job.deleted_at is not None:
        raise HTTPException(409, "A munka már törölve van.")
    if not _can_delete_job(user, job):
        raise HTTPException(403, "Nincs jogod törölni ezt a munkát.")

    if (confirm or "").strip().lower() != "törlés":
        raise HTTPException(400, "A megerősítéshez írd be pontosan: 'törlés' a megfelelő mezőbe.")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(400, "Az indoklás kötelező (legalább 5 karakter).")

    job.deleted_at = utcnow()
    job.deleted_by_id = user.id
    job.delete_reason = reason

    _audit_job(db, user, job, "delete", new=reason)
    db.commit()
    # Törlés után a recycle bin-be visz, hogy lássa hova került
    return RedirectResponse(url="/jobs?view=deleted", status_code=303)


@router.post("/{public_id}/restore")
def jobs_restore(
    public_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _load_job_or_404(db, public_id)

    if job.deleted_at is None:
        raise HTTPException(409, "A munka nincs törölve.")
    if not user.is_admin:
        raise HTTPException(403, "Csak admin tud visszaállítani törölt munkát.")

    old_reason = job.delete_reason
    job.deleted_at = None
    job.deleted_by_id = None
    job.delete_reason = None

    _audit_job(db, user, job, "restore", old=old_reason or "")
    db.commit()
    return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)
