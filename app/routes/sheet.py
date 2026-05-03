"""Munkalap (A4 job sheet) — preview és PDF letöltés.

WeasyPrint rendereli a Jinja2 HTML sablont A4-es PDF-fé.
A preview a böngészőben mutatja ugyanazt a layoutot az app.css
`.a4-sheet` stílusaival, a PDF endpoint letölthető fájlt ad vissza.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modules.jobs.models import Job, JobTask
from app.modules.jobs.public_id import normalize
from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import User
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/sheet", tags=["sheet"])


def _load_job(db: Session, public_id: str) -> Job:
    norm = normalize(public_id)
    if not norm:
        raise HTTPException(404, "Job nem található.")
    job = db.execute(
        select(Job)
        .options(
            selectinload(Job.customer),
            selectinload(Job.tasks).selectinload(JobTask.assigned_to),
            selectinload(Job.intake_user),
        )
        .where(Job.public_id == norm)
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "Job nem található.")
    return job


@router.get("", response_class=HTMLResponse)
def sheet_index(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Munkalap főoldal — egyelőre a job listára irányít."""
    return RedirectResponse(url="/jobs", status_code=302)


@router.get("/{public_id}", response_class=HTMLResponse)
def sheet_preview(
    public_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """A4 munkalap böngészős előnézete az app layouton belül."""
    job = _load_job(db, public_id)
    return templates.TemplateResponse(
        request,
        "jobs/sheet_preview.html",
        {
            "user": user,
            "title": f"Munkalap · {job.public_id[:3]}-{job.public_id[3:]}",
            "topbar_title": "Munkalap",
            "topbar_subtitle": f"{job.public_id[:3]}-{job.public_id[3:]}",
            "job": job,
            **sidebar_context(db, user, active_key="data_sheet"),
        },
    )


@router.get("/{public_id}/pdf")
def sheet_pdf(
    public_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """WeasyPrint-tel renderelt A4 PDF letöltése."""
    import weasyprint

    job = _load_job(db, public_id)

    html_str = templates.get_template("jobs/sheet_a4.html").render(job=job)

    pdf_bytes = weasyprint.HTML(string=html_str).write_pdf()

    filename = f"munkalap_{job.public_id[:3]}-{job.public_id[3:]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
