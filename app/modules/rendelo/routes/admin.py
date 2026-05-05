"""Rendelő modul admin route-jai: kategóriák és tételek (item-katalógus) CRUD.

URL-prefix `/admin/rendelo/...`, csak `is_admin` flag-gel hozzáférhető.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.rendelo.models import Category, Item
from app.shared.db import get_db
from app.shared.dependencies import require_admin
from app.shared.models import User
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/admin/rendelo", tags=["admin-rendelo"])


# ───────────────────────── categories ─────────────────────────


@router.get("/categories", response_class=HTMLResponse)
def categories_list(
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    error: str | None = Query(None),
) -> HTMLResponse:
    cats = db.execute(select(Category).order_by(Category.sort_order, Category.name)).scalars().all()
    item_counts_rows = db.execute(
        select(Item.category_id, func.count())
        .where(Item.active.is_(True))
        .group_by(Item.category_id)
    ).all()
    item_counts = dict(item_counts_rows)
    return templates.TemplateResponse(
        request,
        "rendelo_admin/categories.html",
        {
            "user": user,
            "title": "Kategóriák",
            "topbar_title": "Kategóriák",
            "topbar_subtitle": "Rendelő modul · katalógus-csoportok",
            "categories": cats,
            "item_counts": item_counts,
            "error": error,
            **sidebar_context(db, user, active_key="admin_rendelo_categories"),
        },
    )


@router.post("/categories/new")
def categories_new(
    name: str = Form(...),
    color: str = Form("#8A8474"),
    sort_order: int = Form(0),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    name = (name or "").strip()
    if not name:
        return RedirectResponse(
            url="/admin/rendelo/categories?error=A+n%C3%A9v+k%C3%B6telez%C5%91",
            status_code=303,
        )
    existing = db.execute(select(Category).where(Category.name == name)).scalar_one_or_none()
    if existing is not None:
        return RedirectResponse(
            url="/admin/rendelo/categories?error=Ilyen+nev%C5%B1+kateg%C3%B3ria+m%C3%A1r+van",
            status_code=303,
        )
    db.add(Category(name=name, color=color, sort_order=sort_order))
    db.commit()
    return RedirectResponse(url="/admin/rendelo/categories", status_code=303)


@router.post("/categories/{cat_id}/update")
def categories_update(
    cat_id: int,
    name: str = Form(...),
    color: str = Form("#8A8474"),
    sort_order: int = Form(0),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    cat = db.get(Category, cat_id)
    if cat is None:
        raise HTTPException(404, "Kategória nem található.")
    cat.name = (name or cat.name).strip() or cat.name
    cat.color = color or cat.color
    cat.sort_order = sort_order
    db.commit()
    return RedirectResponse(url="/admin/rendelo/categories", status_code=303)


@router.post("/categories/{cat_id}/delete")
def categories_delete(
    cat_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    cat = db.get(Category, cat_id)
    if cat is None:
        raise HTTPException(404, "Kategória nem található.")
    item_count = (
        db.execute(
            select(func.count()).select_from(Item).where(Item.category_id == cat_id)
        ).scalar()
        or 0
    )
    if item_count > 0:
        return RedirectResponse(
            url=f"/admin/rendelo/categories?error=Nem+t%C3%B6r%C3%B6lhet%C5%91+%E2%80%94+{item_count}+t%C3%A9tel+haszn%C3%A1lja",
            status_code=303,
        )
    db.delete(cat)
    db.commit()
    return RedirectResponse(url="/admin/rendelo/categories", status_code=303)


# ───────────────────────── items ─────────────────────────


@router.get("/items", response_class=HTMLResponse)
def items_list(
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    cat: int | None = Query(None),
    show_inactive: bool = False,
) -> HTMLResponse:
    cats = db.execute(select(Category).order_by(Category.sort_order, Category.name)).scalars().all()
    stmt = select(Item).order_by(Item.name)
    if cat is not None:
        stmt = stmt.where(Item.category_id == cat)
    if not show_inactive:
        stmt = stmt.where(Item.active.is_(True))
    items = db.execute(stmt).scalars().all()
    return templates.TemplateResponse(
        request,
        "rendelo_admin/items.html",
        {
            "user": user,
            "title": "Tételek",
            "topbar_title": "Tételek",
            "topbar_subtitle": "Rendelő modul · katalógus",
            "items": items,
            "categories": cats,
            "active_cat": cat,
            "show_inactive": show_inactive,
            **sidebar_context(db, user, active_key="admin_rendelo_items"),
        },
    )


@router.get("/items/new", response_class=HTMLResponse)
def items_new_form(
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    error: str | None = Query(None),
) -> HTMLResponse:
    cats = db.execute(select(Category).order_by(Category.sort_order, Category.name)).scalars().all()
    if not cats:
        return RedirectResponse(
            url="/admin/rendelo/categories?error=El%C5%91sz%C3%B6r+vegy%C3%A9l+fel+kateg%C3%B3ri%C3%A1t",
            status_code=303,
        )
    return templates.TemplateResponse(
        request,
        "rendelo_admin/item_form.html",
        {
            "user": user,
            "title": "Új tétel",
            "topbar_title": "Új tétel",
            "categories": cats,
            "item": None,
            "error": error,
            **sidebar_context(db, user, active_key="admin_rendelo_items"),
        },
    )


@router.post("/items/new")
def items_new_submit(
    name: str = Form(...),
    category_id: int = Form(...),
    brand: str | None = Form(None),
    code: str | None = Form(None),
    sizes: str | None = Form(None),
    description: str | None = Form(None),
    supplier: str | None = Form(None),
    default_unit: str = Form("db"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    name = (name or "").strip()
    if not name:
        return RedirectResponse(
            url="/admin/rendelo/items/new?error=A+n%C3%A9v+k%C3%B6telez%C5%91", status_code=303
        )
    if db.get(Category, category_id) is None:
        raise HTTPException(400, "Ismeretlen kategória.")
    item = Item(
        name=name,
        category_id=category_id,
        brand=(brand or "").strip() or None,
        code=(code or "").strip() or None,
        sizes=(sizes or "").strip() or None,
        description=(description or "").strip() or None,
        supplier=(supplier or "").strip() or None,
        default_unit=(default_unit or "db").strip() or "db",
        active=True,
    )
    db.add(item)
    db.commit()
    return RedirectResponse(url="/admin/rendelo/items", status_code=303)


@router.get("/items/{item_id}", response_class=HTMLResponse)
def items_edit_form(
    item_id: int,
    request: FastAPIRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    error: str | None = Query(None),
) -> HTMLResponse:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Tétel nem található.")
    cats = db.execute(select(Category).order_by(Category.sort_order, Category.name)).scalars().all()
    return templates.TemplateResponse(
        request,
        "rendelo_admin/item_form.html",
        {
            "user": user,
            "title": "Tétel szerkesztése",
            "topbar_title": item.name,
            "topbar_subtitle": "tétel szerkesztése",
            "categories": cats,
            "item": item,
            "error": error,
            **sidebar_context(db, user, active_key="admin_rendelo_items"),
        },
    )


# ───────────────────────── items: CSV bulk-import ─────────────────────────


@router.post("/items/import-csv", response_class=HTMLResponse)
async def items_import_csv(
    request: FastAPIRequest,
    csv_file: UploadFile = File(...),
    dry_run: str | None = Form(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Item katalógus CSV bulk-import. `dry_run=on` → nem ment, csak validál."""
    from app.modules.rendelo.csv_import import import_csv

    raw = await csv_file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-2")  # HU Excel default
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")

    is_dry = dry_run == "on"
    stats = import_csv(db, text, dry_run=is_dry)

    cats = db.execute(select(Category).order_by(Category.sort_order, Category.name)).scalars().all()
    items = db.execute(
        select(Item).where(Item.active.is_(True)).order_by(Item.name)
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "rendelo_admin/items.html",
        {
            "user": user,
            "title": "Tételek",
            "topbar_title": "Tételek",
            "topbar_subtitle": "Rendelő modul · katalógus",
            "items": items,
            "categories": cats,
            "active_cat": None,
            "show_inactive": False,
            "csv_stats": stats,
            "csv_dry_run": is_dry,
            **sidebar_context(db, user, active_key="admin_rendelo_items"),
        },
    )


@router.post("/items/{item_id}/update")
def items_update(
    item_id: int,
    name: str = Form(...),
    category_id: int = Form(...),
    brand: str | None = Form(None),
    code: str | None = Form(None),
    sizes: str | None = Form(None),
    description: str | None = Form(None),
    supplier: str | None = Form(None),
    default_unit: str = Form("db"),
    active: str | None = Form(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Tétel nem található.")
    item.name = (name or item.name).strip() or item.name
    item.category_id = category_id
    item.brand = (brand or "").strip() or None
    item.code = (code or "").strip() or None
    item.sizes = (sizes or "").strip() or None
    item.description = (description or "").strip() or None
    item.supplier = (supplier or "").strip() or None
    item.default_unit = (default_unit or "db").strip() or "db"
    item.active = active == "on"
    db.commit()
    return RedirectResponse(url="/admin/rendelo/items", status_code=303)
