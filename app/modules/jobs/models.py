"""Munkák modul tábla-schemái.

A Customer (ügyféltábla) közös, az `app.shared.models`-ben él. Itt csak
a Munkák-specifikus táblák: `jobs`, `job_tasks`, `job_attachments`.
Mindegyiknek `jobs_` prefixe van, hogy ne ütközzenek a Készlet modul
jövőbeli tábláival.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db import Base
from app.shared.models import Customer, User, utcnow


class IntakeChannel(StrEnum):
    """Hogyan került be a munka a rendszerbe."""

    PERSONAL = "personal"
    EMAIL = "email"
    WORKSHOP_DROPOFF = "workshop_dropoff"
    PHONE = "phone"


class JobStatus(StrEnum):
    """A Job életciklusa.

    `felvett` → `grafikan` → `kesz_latvany` → [`ugyfel_jovahagyas_var`] →
    `muhelyben` → `kesz` → `atadva`. A `visszahivva` mellék-állapot:
    ha `kesz`-en >X napig áll és nem viszik el, ide kerül.
    """

    FELVETT = "felvett"
    GRAFIKAN = "grafikan"
    KESZ_LATVANY = "kesz_latvany"
    UGYFEL_JOVAHAGYAS_VAR = "ugyfel_jovahagyas_var"
    MUHELYBEN = "muhelyben"
    KESZ = "kesz"
    ATADVA = "atadva"
    VISSZAHIVVA = "visszahivva"


class TaskType(StrEnum):
    """Egy job_task gép-típusa. A spec 12 értéket sorol fel; ha új gép-típus
    érkezik, ide bővítjük."""

    UV_PRINT = "uv_print"
    CO2_LASER = "co2_laser"
    FIBER_LASER = "fiber_laser"
    DTF_PRINT = "dtf_print"
    DTF_PRESS = "dtf_press"
    MUG_PRESS = "mug_press"
    ENGRAVE_MANUAL = "engrave_manual"
    STAMP = "stamp"
    BUSINESS_CARD = "business_card"
    STICKER = "sticker"
    LARGE_FORMAT = "large_format"
    OTHER = "other"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class AttachmentKind(StrEnum):
    SOURCE = "source"
    PREVIEW = "preview"


class Job(Base):
    """A munkalap fő entitása. Egy ügyfél-megrendelés egy Job, akkor is ha
    több gépen készül.

    A `public_id` a `XXX-XXX` formátumú 6-karakteres azonosító (kötőjel
    nélkül tárolva, megjelenítéskor formázva). A generálás retry-jal
    biztosítja az egyediséget; lásd `app.modules.jobs.public_id`.
    """

    __tablename__ = "jobs_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    intake_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    intake_channel: Mapped[IntakeChannel] = mapped_column(String(20), nullable=False)
    # Email-csatornás munkáknál a forrás-incoming_email rekord; a tábla
    # később, Fázis 4-ben jön be (`incoming_emails`). FK-szabály SET NULL,
    # de a tábla még nem létezik — egyelőre simán int kulcs, FK constraint
    # akkor jön be amikor az incoming_emails tábla felépül.
    source_email_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_designer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    is_urgent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_huf: Mapped[int | None] = mapped_column(Integer, nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[JobStatus] = mapped_column(
        String(30), nullable=False, default=JobStatus.FELVETT, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped[Customer] = relationship()
    intake_user: Mapped[User] = relationship(foreign_keys=[intake_user_id])
    assigned_designer: Mapped[User | None] = relationship(foreign_keys=[assigned_designer_id])
    tasks: Mapped[list[JobTask]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobTask.id",
    )
    attachments: Mapped[list[JobAttachment]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobAttachment.uploaded_at",
    )


class JobTask(Base):
    """Egy task = egy gyártási lépés egy géppel/típussal.

    Egy bögre+póló-rendelés 2 task; egy gravírozott fa 1 task. A Job
    akkor lép `kesz` állapotba, amikor minden task `done`.
    """

    __tablename__ = "jobs_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_type: Mapped[TaskType] = mapped_column(String(30), nullable=False, index=True)
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[TaskStatus] = mapped_column(
        String(20), nullable=False, default=TaskStatus.PENDING, index=True
    )
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    job: Mapped[Job] = relationship(back_populates="tasks")
    assigned_to: Mapped[User | None] = relationship()


class JobAttachment(Base):
    """Egy Job-hoz tartozó fájl: forrásfájl (Corel/Illustrator) vagy a
    Corel-makró által generált preview PNG.

    A `page_index` csak preview-knél: többoldalas Corel doc-nál minden
    oldalra külön preview.
    """

    __tablename__ = "jobs_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[AttachmentKind] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    page_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped[Job] = relationship(back_populates="attachments")
