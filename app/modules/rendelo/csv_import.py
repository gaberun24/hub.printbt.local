"""Tételek CSV-ből importálása.

Elvárt CSV oszlopok (header sor kötelező; UTF-8 kódolás, vessző- vagy
pontosvessző-elválasztás auto-detektálva):

    name           — kötelező
    category       — kötelező, a `Category.name`-mel egyezik (kis-nagybetű érzéketlen)
    brand          — opcionális
    code           — opcionális (cikkszám)
    sizes          — opcionális (pl. "XS-5XL")
    description    — opcionális
    supplier       — opcionális
    default_unit   — opcionális (default: "db")

Egyezéskeresés:
    1. brand + code (ha mindkettő megvan)
    2. különben name + category_id

Idempotens — meglévő egyezést frissít.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.rendelo.models import Category, Item

REQUIRED_COLUMNS = {"name", "category"}


@dataclass
class CsvImportStats:
    rows_seen: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _detect_dialect(sample: str) -> csv.Dialect | type[csv.Dialect]:
    """Vessző vs pontosvessző — Excel HU/EU pontosvesszővel exportál."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def import_csv(db: Session, csv_text: str, *, dry_run: bool = False) -> CsvImportStats:
    """CSV szöveg → Item rekordok.

    A `csv_text` UTF-8 sztring. Bytes-ot a hívónak kell előbb dekódolnia.
    """
    stats = CsvImportStats()

    csv_text = csv_text.strip()
    if not csv_text:
        stats.errors.append("Üres CSV.")
        return stats

    # BOM eltávolítás (Excel néha UTF-8 BOM-mal exportál)
    if csv_text.startswith("﻿"):
        csv_text = csv_text[1:]

    sample = csv_text[:2048]
    dialect = _detect_dialect(sample)

    reader = csv.DictReader(io.StringIO(csv_text), dialect=dialect)
    if not reader.fieldnames:
        stats.errors.append("Nincs header sor.")
        return stats

    headers = {h.strip().lower(): h for h in reader.fieldnames}
    missing = REQUIRED_COLUMNS - set(headers.keys())
    if missing:
        stats.errors.append(f"Hiányzó kötelező oszlopok: {', '.join(sorted(missing))}")
        return stats

    cat_by_name = {c.name.lower(): c for c in db.execute(select(Category)).scalars().all()}

    def _get(row: dict, col: str) -> str:
        return (row.get(headers.get(col, ""), "") or "").strip()

    for line_no, row in enumerate(reader, start=2):  # start=2: header után
        stats.rows_seen += 1

        name = _get(row, "name")
        category_name = _get(row, "category")

        if not name:
            stats.errors.append(f"{line_no}. sor: hiányzó name")
            stats.skipped += 1
            continue
        if not category_name:
            stats.errors.append(f"{line_no}. sor: hiányzó category ('{name}')")
            stats.skipped += 1
            continue

        category = cat_by_name.get(category_name.lower())
        if category is None:
            stats.errors.append(
                f"{line_no}. sor: ismeretlen kategória '{category_name}' ('{name}')"
            )
            stats.skipped += 1
            continue

        brand = _get(row, "brand") or None
        code = _get(row, "code") or None
        sizes = _get(row, "sizes") or None
        description = _get(row, "description") or None
        supplier = _get(row, "supplier") or None
        default_unit = _get(row, "default_unit") or "db"

        existing = None
        if brand and code:
            existing = db.execute(
                select(Item).where(Item.brand == brand, Item.code == code)
            ).scalar_one_or_none()
        if existing is None:
            existing = db.execute(
                select(Item).where(Item.name == name, Item.category_id == category.id)
            ).scalar_one_or_none()

        if existing is not None:
            existing.name = name
            existing.brand = brand
            existing.code = code
            existing.sizes = sizes
            existing.description = description
            existing.supplier = supplier
            existing.default_unit = default_unit
            existing.category_id = category.id
            stats.updated += 1
        else:
            db.add(
                Item(
                    name=name,
                    brand=brand,
                    code=code,
                    sizes=sizes,
                    description=description,
                    supplier=supplier,
                    default_unit=default_unit,
                    category_id=category.id,
                    active=True,
                )
            )
            stats.added += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return stats
