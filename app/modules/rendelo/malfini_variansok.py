"""Malfini variant-CSV importer (saját formátum).

A `nyomda_rendelo` exportált CSV-jét olvassa, NEM a Malfini Standard
Pricelist-et. Oszlopok (UTF-8 BOM elfogadva, pontosvessző-elválasztás):

    code;model_code;color_code;size_code;
    model_label;color_label;color_hex;size_label;
    name;category;stock_qty;stock_fetched_at;active

Egy sor egy konkrét variant-Item: a 7-jegyű cikkszám az `Item.code`,
a teljes név az `Item.name`, a kategória név-szerinti egyezésre (Póló).
A `active="igen"` aktív rekord, "nem" → inaktív. A `stock_qty` és
`stock_fetched_at` az utolsó ismert állapot — a `refresh-malfini-stock`
parancs felülírja a következő poll-on.

A CSV-ben NEM szereplő meglévő Malfini-Item-eket DEACTIVATE-eljük
(ha a `deactivate_missing=True`) — így csak a ti modelljeitek
maradnak aktívak az autocomplete-ben és cascade dropdown-ban.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.rendelo.models import Category, Item

EXPECTED_COLUMNS = {
    "code",
    "model_code",
    "color_code",
    "size_code",
    "model_label",
    "color_label",
    "color_hex",
    "size_label",
    "name",
    "category",
    "stock_qty",
    "stock_fetched_at",
    "active",
}
REQUIRED_COLUMNS = {"code", "name", "category"}


@dataclass
class VariantImportStats:
    rows_seen: int = 0
    added: int = 0
    updated: int = 0
    skipped_invalid: int = 0
    deactivated: int = 0
    by_category: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)


def _parse_datetime(raw: str) -> datetime | None:
    """'2026-05-05 13:30' / '2026-05-05T13:30:00' / 'YYYY-MM-DD' → naive datetime."""
    s = (raw or "").strip()
    if not s:
        return None
    # Próbáljuk több formátummal
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # ISO format fallback
    try:
        return datetime.fromisoformat(s.replace(" ", "T"))
    except ValueError:
        return None


def _parse_int(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def import_variansok_csv(
    db: Session,
    csv_path: str | Path,
    *,
    deactivate_missing: bool = True,
    dry_run: bool = False,
) -> VariantImportStats:
    """Saját Malfini-variansok CSV → Item rekordok (brand=Malfini).

    Args:
        csv_path: a CSV fájl elérési útja
        deactivate_missing: True (default) → CSV-ben nem szereplő meglévő
            Malfini-Item-eket `active=False`-ra állítjuk
        dry_run: True → nem commit-ol

    Returns:
        VariantImportStats — részletes eredmény.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise ValueError(f"CSV nem létezik: {csv_path}")

    stats = VariantImportStats()

    # Kategória cache (név → id), case-insensitive
    cat_by_name: dict[str, Category] = {
        c.name.lower(): c for c in db.execute(select(Category)).scalars().all()
    }

    # Meglévő Malfini-Item-ek code szerint
    existing_q = select(Item).where(func.lower(Item.brand) == "malfini")
    existing_items = list(db.execute(existing_q).scalars())
    existing_by_code: dict[str, Item] = {it.code: it for it in existing_items if it.code}

    seen_codes: set[str] = set()

    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        if not reader.fieldnames:
            stats.errors.append("Nincs header sor.")
            return stats

        # Header normalizálás
        headers = {h.strip().lower(): h for h in reader.fieldnames}
        missing = REQUIRED_COLUMNS - set(headers.keys())
        if missing:
            stats.errors.append(f"Hiányzó kötelező oszlopok: {', '.join(sorted(missing))}")
            return stats

        def _get(row: dict, col: str) -> str:
            return (row.get(headers.get(col, ""), "") or "").strip()

        for line_no, row in enumerate(reader, start=2):
            stats.rows_seen += 1

            code = _get(row, "code")
            name = _get(row, "name")
            category_name = _get(row, "category")

            if not code or not name or not category_name:
                stats.skipped_invalid += 1
                stats.errors.append(
                    f"{line_no}. sor: hiányzó code/name/category"
                )
                continue

            if code in seen_codes:
                stats.skipped_invalid += 1
                continue
            seen_codes.add(code)

            category = cat_by_name.get(category_name.lower())
            if category is None:
                stats.skipped_invalid += 1
                stats.errors.append(
                    f"{line_no}. sor: ismeretlen kategória '{category_name}' "
                    f"(code={code}). Futtasd először: hub seed-rendelo-categories"
                )
                continue

            stats.by_category[category.name] += 1

            stock_qty = _parse_int(_get(row, "stock_qty"))
            stock_fetched_at = _parse_datetime(_get(row, "stock_fetched_at"))
            active_raw = _get(row, "active").lower()
            is_active = active_raw in ("igen", "1", "true", "yes")

            # color_label és size_label nincs külön mező az Item-en, de a `name`
            # és a `code` már tartalmazza őket — a malfini_parser ki tudja
            # szedni runtime-ban a cascade dropdown-hoz.

            existing = existing_by_code.get(code)
            if existing is not None:
                existing.name = name
                existing.category_id = category.id
                existing.brand = "Malfini"
                existing.supplier = "Malfini"
                existing.default_unit = "db"
                existing.active = is_active
                if stock_qty is not None:
                    existing.stock_qty = stock_qty
                if stock_fetched_at is not None:
                    existing.stock_fetched_at = stock_fetched_at
                stats.updated += 1
            else:
                db.add(
                    Item(
                        name=name,
                        category_id=category.id,
                        brand="Malfini",
                        code=code,
                        supplier="Malfini",
                        default_unit="db",
                        active=is_active,
                        stock_qty=stock_qty,
                        stock_fetched_at=stock_fetched_at,
                    )
                )
                stats.added += 1

    # Régi Malfini Item-ek deaktiválása amik nem szerepelnek a CSV-ben
    if deactivate_missing:
        for it in existing_items:
            if it.code and it.code not in seen_codes and it.active:
                it.active = False
                stats.deactivated += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return stats
