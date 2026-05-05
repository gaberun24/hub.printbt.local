"""Email integráció adatmodellje — email_accounts, incoming_emails, email_attachments.

Ezek a Munkák modul részeként élnek, mert az emailek alapvetően
munkafelvételi csatornát biztosítanak. A `email_accounts` táblát
csak a superadmin kezeli (Fázis 4 — /system/email-accounts UI).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db import Base
from app.shared.models import Customer, User, utcnow

# Many-to-many: melyik user-ek látják az adott email fiókot.
# Ha egy fiókhoz NINCS egyetlen user sem rendelve → közös, mindenki látja.
email_account_viewers = Table(
    "email_account_viewers",
    Base.metadata,
    Column("account_id", Integer, ForeignKey("email_accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class EmailCategory(StrEnum):
    """Email kategória — Python előszűrő vagy Gemini dönti.

    Pipeline: ismert ügyfél → ismert szállító domain → spam pattern
    → Gemini flash (ami maradt). Lásd README Fázis 4.
    """

    WORK = "work"  # Munkafelvétel (új job)
    QUOTE_REQUEST = "quote_request"  # Árajánlat-kérés
    SUPPLIER = "supplier"  # Szállítói (rendelés-visszaigazolás, szállítás, számla)
    OTHER = "other"  # Egyéb (kérdés, visszajelzés, stb.)
    SPAM = "spam"  # Spam / irreleváns


class ClassifiedBy(StrEnum):
    """Ki/mi döntötte el a kategóriát?"""

    RULE_CUSTOMER = "rule_customer"  # Python: ismert ügyfél email
    RULE_SUPPLIER = "rule_supplier"  # Python: ismert szállító domain
    RULE_SPAM = "rule_spam"  # Python: spam pattern (unsubscribe, stb.)
    RULE_FALLBACK = "rule_fallback"  # Default OTHER, ha AI nem elérhető
    GEMINI = "gemini"  # Google Gemini Flash API (felhő)
    LM_STUDIO = "lm_studio"  # Helyi LM Studio (OpenAI-kompatibilis)
    MANUAL = "manual"  # User kézi átsorolás


class EmailAccount(Base):
    """IMAP fiók konfiguráció — superadmin kezeli.

    A jelszó a SECRET_KEY-vel titkosítva tárolódik
    (`imap_password_encrypted`). Egyelőre plaintext fallback
    is van a korai fejlesztéshez — éles előtt cserélni kell.
    """

    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    email_address: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    imap_host: Mapped[str] = mapped_column(String(200), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    imap_user: Mapped[str] = mapped_column(String(200), nullable=False)
    imap_password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    imap_use_ssl: Mapped[bool] = mapped_column(default=True)

    smtp_host: Mapped[str | None] = mapped_column(String(200), nullable=True)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_user: Mapped[str | None] = mapped_column(String(200), nullable=True)
    smtp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_use_tls: Mapped[bool] = mapped_column(default=True)

    # Melyik user-ek látják ezt a fiókot. Ha üres → közös, mindenki látja.
    viewers: Mapped[list[User]] = relationship(secondary=email_account_viewers)

    active: Mapped[bool] = mapped_column(default=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_poll_uid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IncomingEmail(Base):
    """Egy bejövő email — az IMAP poller hozza létre, Gemini kategorizálja."""

    __tablename__ = "incoming_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("email_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)

    from_address: Mapped[str] = mapped_column(String(300), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    to_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Email szál (válasz-lánc követéshez)
    in_reply_to: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)

    # ── Kategorizáció ──
    # Az érvényes kategória: manual > gemini > rule
    category: Mapped[EmailCategory | None] = mapped_column(
        String(30), nullable=True, index=True
    )
    classified_by: Mapped[ClassifiedBy | None] = mapped_column(
        String(30), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(nullable=True)

    # Gemini-specifikus mezők (csak ha classified_by == gemini)
    gemini_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Manuális felülbírálás — ha a user átsorolja
    manual_category: Mapped[EmailCategory | None] = mapped_column(
        String(30), nullable=True
    )
    manual_category_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Ismert ügyfél match
    matched_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )

    # Irány — True ha mi küldtük (válasz/compose), False ha bejövő
    is_outgoing: Mapped[bool] = mapped_column(default=False)
    sent_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Feldolgozás
    is_read: Mapped[bool] = mapped_column(default=False)
    converted_to_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs_jobs.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # IMAP takarítás
    imap_uid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    imap_deleted: Mapped[bool] = mapped_column(default=False)

    # Spam/szállító purge
    purged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    account: Mapped[EmailAccount] = relationship()
    matched_customer: Mapped[Customer | None] = relationship()
    sent_by: Mapped[User | None] = relationship(foreign_keys=[sent_by_user_id])
    attachments: Mapped[list[EmailAttachment]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )

    @property
    def effective_category(self) -> EmailCategory | None:
        """A ténylegesen érvényes kategória: manual felülírja az automata döntést."""
        return self.manual_category or self.category

    @property
    def attachment_count(self) -> int:
        return len(self.attachments) if self.attachments else 0


class ScanStatus(StrEnum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    ERROR = "error"
    SKIPPED = "skipped"


class EmailAttachment(Base):
    """Egy email csatolmánya — a fájl a storage-on él."""

    __tablename__ = "email_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_id: Mapped[int] = mapped_column(
        ForeignKey("incoming_emails.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(20), default=ScanStatus.PENDING)
    scan_result: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    email: Mapped[IncomingEmail] = relationship(back_populates="attachments")

    @property
    def is_safe(self) -> bool:
        return self.scan_status in (ScanStatus.CLEAN, ScanStatus.SKIPPED)
