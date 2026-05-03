"""Munkák modul page-route-jai (Fázis 2.2 — kezdő CRUD).

Most: /jobs (saját + közös pool toggle), /jobs/new (felvétel form), és
/jobs/{public_id} (minimális detail). A teljes mockup-faithful detail
+ státusz-akciók a 2.3-ban jönnek.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Query
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
from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import (
    AuditEntityType,
    AuditLog,
    Customer,
    User,
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
    view: str = Query("own", description="own | pool | all"),
    job_type: str | None = Query(None, description="job_type szűrés"),
) -> HTMLResponse:
    """Saját munkáim / Közös pool / Mind + opcionális job_type szűrés."""

    stmt = (
        select(Job)
        .options(
            selectinload(Job.customer),
            selectinload(Job.tasks),
            selectinload(Job.intake_user),
            selectinload(Job.assigned_designer),
        )
        .where(Job.status.in_(_ACTIVE_STATUSES))
        .order_by(Job.deadline.asc())
    )

    if view == "own":
        stmt = stmt.where(or_(Job.intake_user_id == user.id, Job.assigned_designer_id == user.id))
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
    groups = _group_by_status(jobs)

    return templates.TemplateResponse(
        request,
        "jobs/list.html",
        {
            "user": user,
            "title": view_label,
            "topbar_title": view_label,
            "topbar_subtitle": f"{len(jobs)} aktív munka",
            "view": view,
            "view_label": view_label,
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
    return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)


@router.post("/{public_id}/tasks/{task_id}/done")
def task_done(
    public_id: str,
    task_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = _load_job_or_404(db, public_id)
    task = _get_task(job, task_id)
    task.status = TaskStatus.DONE
    if task.completed_at is None:
        task.completed_at = utcnow()
    if task.assigned_to_user_id is None:
        # Aki done-ra teszi, az legyen rögzítve a felelős
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
    return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)


@router.post("/{public_id}/tasks/{task_id}/release")
def task_release(
    public_id: str,
    task_id: int,
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
    return RedirectResponse(url=f"/jobs/{job.public_id}", status_code=303)


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
