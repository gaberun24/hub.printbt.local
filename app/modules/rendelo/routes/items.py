"""Tételek (katalógus) közfelületei — autocomplete és Malfini cascading tree.

Az admin Item CRUD a `app.modules.rendelo.routes.admin`-ban él. Itt csak a
non-admin felhasználói oldal van: autocomplete + a Póló-kategóriás
cascading dropdownnak adatot szolgáltató endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.rendelo.malfini_parser import (
    get_color_hex,
    parse_malfini_name,
    size_sort_key,
)
from app.modules.rendelo.models import Category, Item
from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import User
from app.shared.templates import templates

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/search")
def search(
    request: Request,
    q: str = "",
    user: User = Depends(current_user),  # noqa: ARG001 — auth gate
    db: Session = Depends(get_db),
):
    """Autocomplete suggestions a new request űrlapnak.

    Csak az aktív tételeket adja vissza, max 8-at. A keresés case-insensitive,
    a name + brand + code mezők bármelyikében matcheli a `q`-t.
    Üres `q` → üres válasz (nem akarjuk szuggesztálni a teljes katalógust).

    Ha a query 3-jegyű szám (pl. "134"), a Malfini model-prefix találatok
    előrébb kerülnek mint a substring-talált 8-jegyű kódok.
    """
    q_clean = q.strip()
    items: list[Item] = []
    if len(q_clean) >= 2:
        like = f"%{q_clean.lower()}%"
        is_model_code = q_clean.isdigit() and len(q_clean) == 3
        if is_model_code:
            # Modell-szám találatok előre — a kódjuk pontos prefixszel kezdődik
            prefix_like = f"{q_clean}%"
            stmt = (
                select(Item)
                .where(
                    Item.active.is_(True),
                    or_(
                        Item.code.like(prefix_like),
                        func.lower(Item.name).like(like),
                        func.lower(Item.brand).like(like),
                    ),
                )
                .order_by(
                    # Először a model-prefix matchek (rövidebb code → korábbi)
                    Item.code.like(prefix_like).desc(),
                    Item.brand.is_(None),
                    Item.brand,
                    Item.name,
                )
                .limit(8)
            )
        else:
            stmt = (
                select(Item)
                .where(
                    Item.active.is_(True),
                    or_(
                        func.lower(Item.name).like(like),
                        func.lower(Item.brand).like(like),
                        func.lower(Item.code).like(like),
                    ),
                )
                .order_by(Item.brand.is_(None), Item.brand, Item.name)
                .limit(8)
            )
        items = list(db.execute(stmt).scalars().all())

    return templates.TemplateResponse(
        request,
        "rendelo/_item_suggestions.html",
        {"items": items, "query": q_clean},
    )


@router.get("/malfini-tree")
def malfini_tree(
    category_id: int | None = None,
    user: User = Depends(current_user),  # noqa: ARG001 — auth gate
    db: Session = Depends(get_db),
):
    """Cascading dropdownnak: model → color → size, csak Malfini brand-re.

    A választott kategória aktív Malfini Item-jeit veszi, és az
    `app.modules.rendelo.malfini_parser` segítségével felépíti a hierarchikus fát.
    """
    stmt = select(Item).where(
        Item.active.is_(True),
        func.lower(Item.brand) == "malfini",
    )
    if category_id is not None:
        stmt = stmt.where(Item.category_id == category_id)

    items = db.execute(stmt).scalars().all()

    # Kétszintű lookup: model_code → color_code → list[size]
    tree: dict[str, dict] = {}
    for it in items:
        if not it.code or len(it.code) < 7:
            continue
        parsed = parse_malfini_name(it.name)
        if parsed is None:
            continue

        # A 7-jegyű cikkszám: <model:3><color:2><size:2>. A 215A216 mintánál
        # is működik mert csak az első 5-et tudjuk biztosan hivatkozni
        # (model + color), a méretet a parsolt `size_label` adja.
        model_code = it.code[:3]
        color_code = it.code[3:5]

        m = tree.setdefault(
            model_code,
            {"code": model_code, "label": parsed.model_label, "colors": {}},
        )
        c = m["colors"].setdefault(
            color_code,
            {
                "code": color_code,
                "label": parsed.color_label,
                "hex": get_color_hex(parsed.color_label),
                "sizes": [],
            },
        )
        c["sizes"].append(
            {
                "size": parsed.size_label,
                "item_id": it.id,
                "item_code": it.code,
                "item_name": it.name,
                # Stock — None = még sose szinkronizáltunk, 0 = nincs
                "stock_qty": it.stock_qty,
                "stock_fetched_at": (
                    it.stock_fetched_at.isoformat() if it.stock_fetched_at else None
                ),
            }
        )

    # Rendezés és tömbbé alakítás
    output_models = []
    for model_code in sorted(tree):
        m = tree[model_code]
        colors_arr = []
        for color_code in sorted(m["colors"]):
            c = m["colors"][color_code]
            c["sizes"].sort(key=lambda s: size_sort_key(s["size"]))
            colors_arr.append(c)
        output_models.append({**m, "colors": colors_arr})

    return {"models": output_models}


@router.get("/poll-poolo-category-id")
def poll_polo_category_id(
    user: User = Depends(current_user),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    """Visszaadja a "Póló" kategória ID-ját — a frontend cascading-toggle-jéhez.

    A frontend a category select onchange-jén ezt cacheli: ha a kiválasztott
    érték == polo_id, mutatja a cascade UI-t.
    """
    cat = db.execute(select(Category).where(Category.name == "Póló")).scalar_one_or_none()
    return {"polo_category_id": cat.id if cat else None}
