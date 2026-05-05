"""Rendelő modul page-route-jai.

Fázis 1.2-ben lett teljes CRUD: új igény form, részletek nézet,
státusz-átléptetés (order/arrive/cancel), kommentek.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.modules.rendelo.models import (
    Category,
    Event,
    EventAction,
    Request,
    RequestLine,
    RequestStatus,
)
from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import AuditEntityType, AuditLog, User, utcnow
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/rendelo", tags=["rendelo"])


# ───────────────────────── helpers ─────────────────────────


def _summary(db: Session, user: User) -> dict:
    """A Rendelő-oldali 4 summary-card adata."""
    new_count = (
        db.execute(
            select(func.count()).select_from(Request).where(Request.status == RequestStatus.NEW)
        ).scalar()
        or 0
    )
    ordered_count = (
        db.execute(
            select(func.count()).select_from(Request).where(Request.status == RequestStatus.ORDERED)
        ).scalar()
        or 0
    )
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    arrived_month_count = (
        db.execute(
            select(func.count())
            .select_from(Request)
            .where(
                Request.status == RequestStatus.ARRIVED,
                Request.arrived_at >= month_start,
            )
        ).scalar()
        or 0
    )
    own_count = (
        db.execute(
            select(func.count())
            .select_from(Request)
            .where(
                Request.requested_by_id == user.id,
                Request.status.in_([RequestStatus.NEW, RequestStatus.ORDERED]),
            )
        ).scalar()
        or 0
    )
    return {
        "new_count": new_count,
        "ordered_count": ordered_count,
        "arrived_month_count": arrived_month_count,
        "own_count": own_count,
    }


def _categories(db: Session) -> list[Category]:
    return list(
        db.execute(select(Category).order_by(Category.sort_order, Category.name)).scalars().all()
    )


def _audit(
    db: Session,
    user_id: int,
    request_id: int,
    action: str,
    *,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    db.add(
        AuditLog(
            entity_type=AuditEntityType.REQUEST,
            entity_id=request_id,
            action=action,
            old_value=old_value,
            new_value=new_value,
            user_id=user_id,
        )
    )


def _load_request_or_404(db: Session, request_id: int) -> Request:
    stmt = (
        select(Request)
        .options(
            selectinload(Request.lines),
            selectinload(Request.requested_by),
            selectinload(Request.ordered_by),
            selectinload(Request.category),
            selectinload(Request.events).selectinload(Event.user),
        )
        .where(Request.id == request_id)
    )
    obj = db.execute(stmt).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Igény nem található.")
    return obj


def _parse_qty(raw: str) -> Decimal | None:
    """Form-ból érkezett mennyiség: '1', '2.5', '1,5' → Decimal. Üres → None."""
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


# ───────────────────────── list ─────────────────────────


@router.get("", response_class=HTMLResponse)
def rendelo_list(
    request: FastAPIRequest,
    view: str | None = Query(None),
    category: int | None = Query(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """A Rendelő modul főoldala: aktív igények + utolsó hét megérkezett."""

    base_stmt = select(Request).options(
        selectinload(Request.lines),
        selectinload(Request.requested_by),
        selectinload(Request.ordered_by),
        selectinload(Request.category),
    )

    if category is not None:
        base_stmt = base_stmt.where(Request.category_id == category)
    if view == "own":
        base_stmt = base_stmt.where(Request.requested_by_id == user.id)

    active_stmt = base_stmt.where(
        Request.status.in_([RequestStatus.NEW, RequestStatus.ORDERED])
    ).order_by(Request.created_at.desc())
    active_requests = db.execute(active_stmt).scalars().all()

    arrived_cutoff = utcnow() - timedelta(days=7)
    arrived_stmt = (
        base_stmt.where(
            Request.status == RequestStatus.ARRIVED,
            Request.arrived_at >= arrived_cutoff,
        )
        .order_by(Request.arrived_at.desc())
        .limit(10)
    )
    arrived_requests = db.execute(arrived_stmt).scalars().all()

    active_category = None
    if category is not None:
        active_category = db.get(Category, category)

    # Kategóriánkénti bontás a chip-sávhoz: { category_id: {"new": N, "ordered": M, "total": N+M} }
    cat_rows = db.execute(
        select(Request.category_id, Request.status, func.count())
        .where(Request.status.in_([RequestStatus.NEW, RequestStatus.ORDERED]))
        .group_by(Request.category_id, Request.status)
    ).all()
    cat_counts: dict[int, dict[str, int]] = {}
    for cat_id, status_val, n in cat_rows:
        bucket = cat_counts.setdefault(cat_id, {"new": 0, "ordered": 0, "total": 0})
        if str(status_val) == "new":
            bucket["new"] = n
        else:
            bucket["ordered"] = n
        bucket["total"] = bucket["new"] + bucket["ordered"]
    all_total = sum(b["total"] for b in cat_counts.values())
    all_new = sum(b["new"] for b in cat_counts.values())

    categories = _categories(db)

    return templates.TemplateResponse(
        request,
        "rendelo/list.html",
        {
            "user": user,
            "title": "Belső igények",
            "topbar_title": "Belső igények",
            "topbar_subtitle": "Toner, papír, alapanyag — fogyások és rendelések",
            "view": view,
            "active_category": active_category,
            "active_requests": active_requests,
            "arrived_requests": arrived_requests,
            "summary": _summary(db, user),
            "categories": categories,
            "cat_counts": cat_counts,
            "all_total": all_total,
            "all_new": all_new,
            **sidebar_context(db, user, active_key="rendelo_list"),
        },
    )


# ───────────────────────── new ─────────────────────────


@router.get("/new", response_class=HTMLResponse)
def rendelo_new_form(
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    error: str | None = Query(None),
) -> HTMLResponse:
    """Új igény felvevő-form."""
    return templates.TemplateResponse(
        request,
        "rendelo/new.html",
        {
            "user": user,
            "title": "Új igény",
            "topbar_title": "Új igény",
            "topbar_subtitle": "egy új belső rendelés-kérés",
            "categories": _categories(db),
            "error": error,
            **sidebar_context(db, user, active_key="rendelo_list"),
        },
    )


@router.post("/new")
async def rendelo_new_submit(
    request: FastAPIRequest,
    category_id: int = Form(...),
    note: str | None = Form(None),
    line_title: list[str] = Form(default_factory=list),
    line_qty: list[str] = Form(default_factory=list),
    line_unit: list[str] = Form(default_factory=list),
    line_item_id: list[str] = Form(default_factory=list),
    image: UploadFile | None = File(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    if db.get(Category, category_id) is None:
        return RedirectResponse(
            url="/rendelo/new?error=Ismeretlen+kateg%C3%B3ria",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    cleaned: list[tuple[str, Decimal, str, int | None]] = []
    for idx, (raw_title, raw_qty, raw_unit) in enumerate(
        zip(line_title, line_qty, line_unit, strict=False)
    ):
        title = (raw_title or "").strip()
        if not title:
            continue
        qty = _parse_qty(raw_qty) or Decimal("1")
        unit = (raw_unit or "db").strip() or "db"
        # item_id opcionális — autocomplete vagy cascade tölti
        raw_item_id = line_item_id[idx] if idx < len(line_item_id) else ""
        item_id_val: int | None = None
        if raw_item_id and raw_item_id.strip().isdigit():
            item_id_val = int(raw_item_id.strip())
        cleaned.append((title, qty, unit, item_id_val))

    if not cleaned and not (note and note.strip()):
        return RedirectResponse(
            url="/rendelo/new?error=Adj+meg+legal%C3%A1bb+egy+t%C3%A9telt+vagy+megjegyz%C3%A9st",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # Kép feltöltés (opcionális)
    image_path = None
    if image is not None and image.filename:
        from app.modules.rendelo.uploads import save_uploaded_image

        try:
            image_path = save_uploaded_image(image)
        except ValueError as exc:
            return RedirectResponse(
                url=f"/rendelo/new?error=K%C3%A9p+hiba%3A+{exc}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

    req = Request(
        category_id=category_id,
        note=(note or "").strip() or None,
        image_path=image_path,
        requested_by_id=user.id,
        status=RequestStatus.NEW,
    )
    db.add(req)
    db.flush()

    for idx, (title, qty, unit, item_id_val) in enumerate(cleaned, start=1):
        db.add(
            RequestLine(
                request_id=req.id,
                line_no=idx,
                title=title,
                qty=qty,
                unit=unit,
                item_id=item_id_val,
            )
        )

    db.add(
        Event(
            request_id=req.id,
            user_id=user.id,
            action=EventAction.CREATED,
            payload_json=json.dumps(
                {"line_count": len(cleaned), "category_id": category_id}, ensure_ascii=False
            ),
        )
    )
    _audit(db, user.id, req.id, "create", new_value="new")

    db.commit()
    return RedirectResponse(url=f"/rendelo/{req.id}", status_code=status.HTTP_303_SEE_OTHER)


# ───────────────────────── archive (statikus path — ELŐBB mint /{int}) ───


@router.get("/archive", response_class=HTMLResponse)
def rendelo_archive(
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    category: int | None = Query(None),
    q: str | None = Query(None),
) -> HTMLResponse:
    """Lezárt és érkezett igények archívuma. Default 2 év, dátum-szűrőkkel.

    FONTOS: ennek az endpointnak a `/{request_id}` GET ELŐTT kell lennie,
    különben az `archive` string `request_id`-ként parse-olódna és 422-t ad.
    """
    from datetime import datetime

    cutoff = utcnow() - timedelta(days=730)

    stmt = (
        select(Request)
        .options(
            selectinload(Request.lines),
            selectinload(Request.requested_by),
            selectinload(Request.ordered_by),
            selectinload(Request.category),
        )
        .where(Request.status.in_([RequestStatus.ARRIVED, RequestStatus.CANCELLED]))
    )

    parsed_from = None
    parsed_to = None
    if from_date:
        try:
            parsed_from = datetime.fromisoformat(from_date)
        except ValueError:
            parsed_from = None
    if to_date:
        try:
            parsed_to = datetime.fromisoformat(to_date)
            parsed_to = parsed_to.replace(hour=23, minute=59, second=59)
        except ValueError:
            parsed_to = None

    if parsed_from:
        stmt = stmt.where(Request.created_at >= parsed_from)
    else:
        stmt = stmt.where(Request.created_at >= cutoff)
    if parsed_to:
        stmt = stmt.where(Request.created_at <= parsed_to)

    if category is not None:
        stmt = stmt.where(Request.category_id == category)

    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Request.note).like(like),
                func.lower(Request.supplier).like(like),
                func.lower(Request.order_ref).like(like),
            )
        )

    stmt = stmt.order_by(Request.created_at.desc())
    items = db.execute(stmt).scalars().all()

    by_month: dict[str, list[Request]] = {}
    for it in items:
        key = it.created_at.strftime("%Y-%m")
        by_month.setdefault(key, []).append(it)

    return templates.TemplateResponse(
        request,
        "rendelo/archive.html",
        {
            "user": user,
            "title": "Archívum",
            "topbar_title": "Archívum",
            "topbar_subtitle": f"{len(items)} lezárt igény",
            "items": items,
            "by_month": by_month,
            "categories": _categories(db),
            "from_date": from_date or "",
            "to_date": to_date or "",
            "active_category": category,
            "q": q or "",
            **sidebar_context(db, user, active_key="rendelo_archive"),
        },
    )


# ───────────────────────── detail ─────────────────────────


@router.get("/{request_id}", response_class=HTMLResponse)
def rendelo_detail(
    request_id: int,
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    obj = _load_request_or_404(db, request_id)
    return templates.TemplateResponse(
        request,
        "rendelo/detail.html",
        {
            "user": user,
            "title": f"Igény #{obj.id}",
            "topbar_title": f"Igény #{obj.id}",
            "topbar_subtitle": obj.category.name,
            "req": obj,
            **sidebar_context(db, user, active_key="rendelo_list"),
        },
    )


# ───────────────────────── state transitions ─────────────────────────


_NEXT_STATE_LABELS = {
    "ordered": "megrendelt",
    "arrived": "megérkezett",
    "cancelled": "lezárt",
    "reopen": "újranyitott",
}


@router.post("/{request_id}/state")
def rendelo_change_state(
    request_id: int,
    next_status: str = Form(...),
    supplier: str | None = Form(None),
    order_ref: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    obj = _load_request_or_404(db, request_id)
    old_status = obj.status

    if next_status == "ordered":
        if obj.status != RequestStatus.NEW:
            raise HTTPException(409, "Csak `new` státuszból lehet megrendelni.")
        if not (user.is_admin or user.is_orderer):
            raise HTTPException(403, "Nincs rendelő-jogod.")
        obj.status = RequestStatus.ORDERED
        obj.ordered_by_id = user.id
        obj.ordered_at = utcnow()
        if supplier and supplier.strip():
            obj.supplier = supplier.strip()
        if order_ref and order_ref.strip():
            obj.order_ref = order_ref.strip()
        action = EventAction.ORDERED

    elif next_status == "arrived":
        if obj.status not in (RequestStatus.NEW, RequestStatus.ORDERED):
            raise HTTPException(
                409, "Csak `new` vagy `ordered` állapotból lehet megérkezésre állítani."
            )
        if not (user.is_admin or user.is_orderer):
            raise HTTPException(403, "Nincs rendelő-jogod.")
        obj.status = RequestStatus.ARRIVED
        obj.arrived_at = utcnow()
        action = EventAction.ARRIVED

    elif next_status == "cancelled":
        if obj.status in (RequestStatus.ARRIVED, RequestStatus.CANCELLED):
            raise HTTPException(409, "Lezárt vagy érkezett igényt nem lehet újra lezárni.")
        obj.status = RequestStatus.CANCELLED
        action = EventAction.CANCELLED

    elif next_status == "reopen":
        if obj.status != RequestStatus.CANCELLED:
            raise HTTPException(409, "Csak lezártat lehet újranyitni.")
        obj.status = RequestStatus.NEW
        action = EventAction.EDITED

    else:
        raise HTTPException(400, f"Ismeretlen státusz: {next_status}")

    db.add(
        Event(
            request_id=obj.id,
            user_id=user.id,
            action=action,
            payload_json=json.dumps(
                {
                    "from": str(old_status),
                    "to": str(obj.status),
                    "supplier": obj.supplier,
                    "order_ref": obj.order_ref,
                },
                ensure_ascii=False,
            ),
        )
    )
    _audit(
        db, user.id, obj.id, "status_change", old_value=str(old_status), new_value=str(obj.status)
    )
    db.commit()
    return RedirectResponse(url=f"/rendelo/{obj.id}", status_code=status.HTTP_303_SEE_OTHER)


# ───────────────────────── edit + comments ─────────────────────────


@router.get("/{request_id}/edit", response_class=HTMLResponse)
def rendelo_edit_form(
    request_id: int,
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    error: str | None = Query(None),
) -> HTMLResponse:
    """Igény szerkesztése — csak `new` állapotban, és csak a felvevő vagy admin."""
    obj = _load_request_or_404(db, request_id)
    if obj.status != RequestStatus.NEW:
        raise HTTPException(409, "Csak `new` státuszú igényt lehet szerkeszteni.")
    if not (user.is_admin or obj.requested_by_id == user.id):
        raise HTTPException(403, "Csak a felvevő vagy admin szerkesztheti.")

    return templates.TemplateResponse(
        request,
        "rendelo/new.html",
        {
            "user": user,
            "title": f"Igény #{obj.id} szerkesztése",
            "topbar_title": f"#{obj.id} szerkesztése",
            "topbar_subtitle": "csak `új` állapotban szerkeszthető",
            "categories": _categories(db),
            "error": error,
            "edit_request": obj,
            **sidebar_context(db, user, active_key="rendelo_list"),
        },
    )


@router.post("/{request_id}/edit")
async def rendelo_edit_submit(
    request_id: int,
    request: FastAPIRequest,
    category_id: int = Form(...),
    note: str | None = Form(None),
    line_title: list[str] = Form(default_factory=list),
    line_qty: list[str] = Form(default_factory=list),
    line_unit: list[str] = Form(default_factory=list),
    line_item_id: list[str] = Form(default_factory=list),
    image: UploadFile | None = File(None),
    remove_image: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    obj = _load_request_or_404(db, request_id)
    if obj.status != RequestStatus.NEW:
        raise HTTPException(409, "Csak `new` státuszú igényt lehet szerkeszteni.")
    if not (user.is_admin or obj.requested_by_id == user.id):
        raise HTTPException(403, "Csak a felvevő vagy admin szerkesztheti.")

    if db.get(Category, category_id) is None:
        return RedirectResponse(
            url=f"/rendelo/{obj.id}/edit?error=Ismeretlen+kateg%C3%B3ria",
            status_code=303,
        )

    obj.category_id = category_id
    obj.note = (note or "").strip() or None

    # Sorok teljes újraépítése (egyszerűbb mint diff-elni)
    for line in list(obj.lines):
        db.delete(line)
    db.flush()

    for idx, (raw_title, raw_qty, raw_unit) in enumerate(
        zip(line_title, line_qty, line_unit, strict=False)
    ):
        title = (raw_title or "").strip()
        if not title:
            continue
        qty = _parse_qty(raw_qty) or Decimal("1")
        unit = (raw_unit or "db").strip() or "db"
        raw_item_id = line_item_id[idx] if idx < len(line_item_id) else ""
        item_id_val = int(raw_item_id.strip()) if raw_item_id.strip().isdigit() else None
        db.add(
            RequestLine(
                request_id=obj.id,
                line_no=idx + 1,
                title=title,
                qty=qty,
                unit=unit,
                item_id=item_id_val,
            )
        )

    # Kép kezelése
    if remove_image == "on":
        obj.image_path = None
    if image is not None and image.filename:
        from app.modules.rendelo.uploads import save_uploaded_image

        try:
            obj.image_path = save_uploaded_image(image)
        except ValueError as exc:
            return RedirectResponse(
                url=f"/rendelo/{obj.id}/edit?error=K%C3%A9p+hiba%3A+{exc}",
                status_code=303,
            )

    db.add(
        Event(
            request_id=obj.id,
            user_id=user.id,
            action=EventAction.EDITED,
            payload_json=json.dumps({"by": user.name}, ensure_ascii=False),
        )
    )
    _audit(db, user.id, obj.id, "edit")
    db.commit()
    return RedirectResponse(url=f"/rendelo/{obj.id}", status_code=303)


@router.post("/{request_id}/comment")
def rendelo_comment(
    request_id: int,
    body: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    obj = _load_request_or_404(db, request_id)
    body = (body or "").strip()
    if not body:
        return RedirectResponse(url=f"/rendelo/{obj.id}", status_code=status.HTTP_303_SEE_OTHER)

    db.add(
        Event(
            request_id=obj.id,
            user_id=user.id,
            action=EventAction.COMMENTED,
            payload_json=json.dumps({"body": body}, ensure_ascii=False),
        )
    )
    db.commit()
    return RedirectResponse(url=f"/rendelo/{obj.id}", status_code=status.HTTP_303_SEE_OTHER)
