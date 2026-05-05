"""Malfini Standard Pricelist CSV → variant-szintű katalógus.

A Malfini-tól letöltött 'Standard pricelist' CSV (~14,800 sor, mindenki
külön cikkszámmal) variant-szintű `Item`-eket csinál. Egy CSV sor = egy
konkrét (modell + szín + méret) variant a 7-jegyű bulk-rendelési kódjával.

A CSV formátum:
    Kód;Név;CSV.PRICE_LIST.OUTLET;Határ;Ár;Határ;Ár;Határ;Ár;Határ;Ár;Határ;Ár;Határ;Ár
    1000008;Classic póló gyerek fehér 110 cm/4 éves;;1;848.00;...
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.rendelo.models import Category, Item

# A "fontos" Malfini modellek — a CSV `Kód` mezőjének első 3 karaktere.
# A Malfini cikkszáma így van összerakva:
#     <model:3 digit><color:2 digit><size:2 digit>
# Pl. "1348612" = modell 134, szín 86 (garnet), méret 12 (XS).
ESSENTIAL_MODELS: frozenset[str] = frozenset(
    {
        "100",
        "101",
        "102",
        "110",
        "111",
        "119",
        "121",
        "127",
        "128",
        "129",
        "131",
        "132",
        "133",
        "135",
        "136",
        "139",
        "141",
        "142",
        "144",
        "145",
        "149",
        "203",
        "210",
        "212",
        "213",
        "215",
        "216",
    }  # fmt: skip
)

# Magyar keyword-ek a kategória-detektáláshoz az Név mezőből. Sorrend-érzékeny
# (első match nyer). A Malfini túlnyomóan textil → default Póló kategória,
# kivéve sapka/táska/kötény/etc., azokat Reklámajándékba dobjuk.
HU_CATEGORY_RULES: list[tuple[set[str], str]] = [
    (
        {
            "sapka",
            "kalap",
            "táska",
            "taska",
            "öv",
            "ov",
            "esernyő",
            "esernyo",
            "törölköző",
            "torolkozo",
            "kötény",
            "koteny",
        },  # fmt: skip
        "Reklámajándék",
    ),
]
DEFAULT_CATEGORY = "Póló"


def _detect_category(name: str) -> str:
    """Magyar termék-név → kategória név (a `Category.name` szerint)."""
    nl = name.lower()
    for keywords, cat in HU_CATEGORY_RULES:
        if any(kw in nl for kw in keywords):
            return cat
    return DEFAULT_CATEGORY


@dataclass
class CSVImportStats:
    rows_seen: int = 0
    added: int = 0
    updated: int = 0
    skipped_filter: int = 0  # not in essential models
    skipped_invalid: int = 0  # üres kód/név
    deactivated: int = 0  # CSV-ben nem szereplő régi Malfini Item-ek
    by_category: Counter[str] = field(default_factory=Counter)


def import_pricelist_csv(
    db: Session,
    csv_path: str | Path,
    *,
    only_essential: bool = True,
    deactivate_missing: bool = True,
    dry_run: bool = False,
) -> CSVImportStats:
    """Malfini Standard Pricelist CSV import.

    Args:
        csv_path: a CSV fájl elérési útja
        only_essential: True (default) → csak az ESSENTIAL_MODELS
            prefixes kódokat veszi (~2054 sor). False → minden (~14,800).
        deactivate_missing: True (default) → a meglévő Malfini Item-eket,
            amik nem szerepelnek a CSV-ben, `active=False`-ra állítja.
        dry_run: True → nem commit-ol, csak számol.

    Returns:
        CSVImportStats — részletes számolós eredmény.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise ValueError(f"CSV nem létezik: {csv_path}")

    # Kategória name → id lookup
    cat_by_name: dict[str, int] = {c.name: c.id for c in db.execute(select(Category)).scalars()}
    if DEFAULT_CATEGORY not in cat_by_name:
        raise ValueError(
            f"'{DEFAULT_CATEGORY}' kategória nem létezik. "
            f"Először vedd fel az admin UI-n vagy seedeld."
        )

    # Meglévő Malfini Item-ek code szerint
    existing_q = select(Item).where(func.lower(Item.brand) == "malfini")
    existing_items = list(db.execute(existing_q).scalars())
    existing_by_code: dict[str, Item] = {i.code: i for i in existing_items if i.code}

    stats = CSVImportStats()
    seen_codes: set[str] = set()

    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader, None)  # fejléc
        for row in reader:
            stats.rows_seen += 1
            if not row or len(row) < 2:
                stats.skipped_invalid += 1
                continue
            code = (row[0] or "").strip()
            name = (row[1] or "").strip()
            if not code or not name:
                stats.skipped_invalid += 1
                continue
            if only_essential and code[:3] not in ESSENTIAL_MODELS:
                stats.skipped_filter += 1
                continue
            if code in seen_codes:
                stats.skipped_invalid += 1
                continue
            seen_codes.add(code)

            cat_name = _detect_category(name)
            cat_id = cat_by_name.get(cat_name) or cat_by_name[DEFAULT_CATEGORY]
            stats.by_category[cat_name] += 1

            existing = existing_by_code.get(code)
            if existing is not None:
                # Update + biztosan aktív
                existing.name = name
                existing.category_id = cat_id
                existing.brand = "Malfini"
                existing.supplier = "Malfini"
                existing.default_unit = "db"
                existing.active = True
                stats.updated += 1
            else:
                db.add(
                    Item(
                        name=name,
                        category_id=cat_id,
                        brand="Malfini",
                        code=code,
                        supplier="Malfini",
                        default_unit="db",
                        active=True,
                    )
                )
                stats.added += 1

    # Régi Malfini Item-ek deaktiválása amik nem szerepelnek a CSV-ben
    if deactivate_missing:
        for it in existing_items:
            if it.code not in seen_codes and it.active:
                it.active = False
                stats.deactivated += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return stats
