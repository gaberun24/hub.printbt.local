"""Rendelő modul tábla-schemái.

A meglévő `nyomda_rendelo` repó modelljeit emeljük át a Hub közös
DB-jébe. A `User`/`UserSession`/`Invite` már a `app.shared.models`-ban
él — ezekre csak referenciaként hivatkozunk.

A táblanevek `rendelo_` prefixet kapnak, hogy ne ütközzenek a többi
modul (Készlet, Munkák) saját jövőbeli tábláival, és hogy egy
SQL-böngészőben azonnal látsszon, melyik modulé az adat.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db import Base
from app.shared.models import User, utcnow


class RequestStatus(StrEnum):
    NEW = "new"
    ORDERED = "ordered"
    ARRIVED = "arrived"
    CANCELLED = "cancelled"


class EventAction(StrEnum):
    CREATED = "created"
    EDITED = "edited"
    ORDERED = "ordered"
    ARRIVED = "arrived"
    CANCELLED = "cancelled"
    REASSIGNED = "reassigned"
    COMMENTED = "commented"


class Category(Base):
    """Item-kategória a Rendelőben (Toner, Festék, Papír, ...)."""

    __tablename__ = "rendelo_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#8A8474")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    items: Mapped[list[Item]] = relationship(back_populates="category")


class Item(Base):
    """A Rendelő katalógus tétel — tipikus rendelnivalók (toner-fajta,
    papírfajta, póló-modell, ...). Az igények ezeket hivatkozzák
    `request_lines.item_id`-n."""

    __tablename__ = "rendelo_items"
    __table_args__ = (
        UniqueConstraint("name", "category_id", name="uq_rendelo_item_name_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("rendelo_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Brand + code: gyártó és cikk-azonosító. Pl. brand="Malfini", code="129".
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Sizes: szabad-szöveges, pl. "XS-5XL", "S/M/L", "30 ml / 50 ml".
    sizes: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_unit: Mapped[str] = mapped_column(String(32), nullable=False, default="db")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Stock — Malfini B2B API-ból szinkronizált aktuális készlet. NULL = még
    # sose lett szinkronizálva (vagy a Malfini API nem ismerte ezt a kódot).
    # Csak a brand=Malfini + valid code Item-eknél van értelme.
    stock_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    category: Mapped[Category] = relationship(back_populates="items")


class Request(Base):
    """Egy igény: egy beszállítóhoz menő összesített rendelés.

    Egy igényhez tartozhat 1 vagy N tétel (`RequestLine`). A kategória,
    státusz, beszállító, és kép az IGÉNY szintjén él — az orderer egy
    POs-szal rendeli az egészet egy beszállítótól.
    """

    __tablename__ = "rendelo_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("rendelo_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # Pool model: senkihez nincs előre rendelve. Aki "megrendelve"-re állítja
    # az igényt, az lesz az `ordered_by`. NULL amíg új státuszban van.
    ordered_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[RequestStatus] = mapped_column(
        String(20), nullable=False, default=RequestStatus.NEW, index=True
    )
    supplier: Mapped[str | None] = mapped_column(String(200), nullable=True)
    order_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    category: Mapped[Category] = relationship()
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id])
    ordered_by: Mapped[User | None] = relationship(foreign_keys=[ordered_by_id])
    lines: Mapped[list[RequestLine]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="RequestLine.line_no",
    )
    events: Mapped[list[Event]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="Event.created_at"
    )


class RequestLine(Base):
    """Egy tétel egy igényen belül.

    Az igényt egy POs-ban rendeli az orderer, de a részleges szállítás
    sorszinten követhető — nem feltétlen érkezik egyszerre az összes tétel.
    A line `line_no` stabil ordering-et biztosít az UI-on (1, 2, 3, …).
    """

    __tablename__ = "rendelo_request_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("rendelo_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("rendelo_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False, default=Decimal("1"))
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="db")
    qty_ordered: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    qty_arrived: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)

    request: Mapped[Request] = relationship(back_populates="lines")
    item: Mapped[Item | None] = relationship()


class Event(Base):
    """Audit-szerű log egy igényhez: státusz-átléptetések, kommentek, …

    Külön a központi `audit_log`-tól, mert a Rendelő UI-on egy
    timeline-szerű részletes view-ban jelenik meg, payload-dal együtt.
    """

    __tablename__ = "rendelo_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("rendelo_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[EventAction] = mapped_column(String(30), nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    request: Mapped[Request] = relationship(back_populates="events")
    user: Mapped[User | None] = relationship()
