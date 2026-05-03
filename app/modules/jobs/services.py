"""Job state-machine és recompute-helperek.

Az átléptetés szabályait egy hely tartja (`ALLOWED_TRANSITIONS`), így a
route és a worker is ugyanazt használja. A `recompute_job_status` a
task-ok aktuális állapota alapján visszaszámolja a Job státuszát (pl.
amikor egy task "done" lesz, és minden task kész → Job → `kesz`).
"""

from __future__ import annotations

from app.modules.jobs.models import Job, JobStatus, JobTask, TaskStatus
from app.shared.models import utcnow

# Engedélyezett state-átléptetések. Az `is_admin` és a worker-process
# ezektől eltekinthet (audit-ot azonban ezek is generálnak).
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.FELVETT: frozenset({JobStatus.GRAFIKAN, JobStatus.MUHELYBEN, JobStatus.KESZ_LATVANY}),
    JobStatus.GRAFIKAN: frozenset(
        {JobStatus.KESZ_LATVANY, JobStatus.UGYFEL_JOVAHAGYAS_VAR, JobStatus.MUHELYBEN}
    ),
    JobStatus.KESZ_LATVANY: frozenset(
        {JobStatus.UGYFEL_JOVAHAGYAS_VAR, JobStatus.MUHELYBEN, JobStatus.GRAFIKAN}
    ),
    JobStatus.UGYFEL_JOVAHAGYAS_VAR: frozenset({JobStatus.MUHELYBEN, JobStatus.GRAFIKAN}),
    JobStatus.MUHELYBEN: frozenset({JobStatus.KESZ}),
    JobStatus.KESZ: frozenset({JobStatus.ATADVA, JobStatus.VISSZAHIVVA}),
    JobStatus.ATADVA: frozenset(),  # terminal
    JobStatus.VISSZAHIVVA: frozenset({JobStatus.ATADVA}),
}

# Magyar UI-címkék a státusz-pillekhez. (A `status_hu` filter ezt a
# mappinget olvassa, hogy a `kesz_latvany` → `kész látvány` legyen.)
STATUS_LABELS_HU: dict[str, str] = {
    JobStatus.FELVETT.value: "felvett",
    JobStatus.GRAFIKAN.value: "grafikán",
    JobStatus.KESZ_LATVANY.value: "kész látvány",
    JobStatus.UGYFEL_JOVAHAGYAS_VAR.value: "ügyfél jóváhagyás vár",
    JobStatus.MUHELYBEN.value: "műhelyben",
    JobStatus.KESZ.value: "kész",
    JobStatus.ATADVA.value: "átadva",
    JobStatus.VISSZAHIVVA.value: "visszahívva",
}

# CSS-modifier a status-pillhez. A mockup `status-pill {value}` osztályt
# használ — a value-name itt a CSS-szelektor.
STATUS_CLASS: dict[str, str] = {
    JobStatus.FELVETT.value: "felvett",
    JobStatus.GRAFIKAN.value: "grafikan",
    JobStatus.KESZ_LATVANY.value: "kesz_latvany",
    JobStatus.UGYFEL_JOVAHAGYAS_VAR.value: "kesz_latvany",  # azonos színkód
    JobStatus.MUHELYBEN.value: "muhelyben",
    JobStatus.KESZ.value: "kesz",
    JobStatus.ATADVA.value: "atadva",
    JobStatus.VISSZAHIVVA.value: "atadva",
}


def can_transition(current: JobStatus | str, target: JobStatus | str) -> bool:
    """Engedélyezett-e a `current → target` átléptetés?"""
    cur = JobStatus(current) if isinstance(current, str) else current
    tgt = JobStatus(target) if isinstance(target, str) else target
    return tgt in ALLOWED_TRANSITIONS.get(cur, frozenset())


def recompute_job_status(job: Job) -> JobStatus | None:
    """A task-ok állapota alapján számolja vissza a Job státuszt.

    Visszaadja az új státuszt, ha a Job-on változtatott. None ha nincs
    változás. **Mellékhatás:** beállítja `job.status`-t és `job.closed_at`-ot
    ha kell. A `commit`-ot a hívó intézi.

    Szabályok:
    - Ha minden task `done` és a Job `muhelyben`-ben volt → `kesz`
    - Ha legalább egy task `in_progress` és a Job NEM `muhelyben` →
      `muhelyben`
    - Egyébként semmi változás (a státuszt explicit átléptetés vezérli)
    """
    if not job.tasks:
        return None

    all_done = all(t.status == TaskStatus.DONE for t in job.tasks)
    any_in_progress = any(t.status == TaskStatus.IN_PROGRESS for t in job.tasks)

    if all_done and job.status == JobStatus.MUHELYBEN:
        job.status = JobStatus.KESZ
        return JobStatus.KESZ

    if any_in_progress and job.status not in (
        JobStatus.MUHELYBEN,
        JobStatus.KESZ,
        JobStatus.ATADVA,
    ):
        job.status = JobStatus.MUHELYBEN
        return JobStatus.MUHELYBEN

    return None


def mark_task_done(task: JobTask) -> None:
    """Egy task `done`-ra léptetése, completed_at beállítása. A Job
    státusz-recompute-ot a hívónak kell külön meghívnia."""
    task.status = TaskStatus.DONE
    if task.completed_at is None:
        task.completed_at = utcnow()


def mark_job_delivered(job: Job) -> None:
    """Job `atadva`-ra léptetése, closed_at beállítása."""
    job.status = JobStatus.ATADVA
    job.closed_at = utcnow()
