"""Jinja2 templates konfig — közös template-ek a `app/templates/` alatt,
modul-specifikus template-ek pedig a `app/modules/<modul>/templates/` alatt.

A Jinja2 a több template-mappát a ChoiceLoader-rel kezeli: először a
modul saját mappáját nézi (specifitás), aztán a közöset (alap).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

APP_DIR = Path(__file__).resolve().parents[1]
SHARED_TEMPLATES_DIR = APP_DIR / "templates"
MODULE_TEMPLATES_DIRS = [
    APP_DIR / "modules" / "rendelo" / "templates",
    APP_DIR / "modules" / "jobs" / "templates",
    APP_DIR / "modules" / "stock" / "templates",
]


def _build_loader() -> ChoiceLoader:
    # Modul-specifikus mappák először (konkrétabbak), aztán a közös.
    loaders = [FileSystemLoader(str(d)) for d in MODULE_TEMPLATES_DIRS if d.exists()]
    loaders.append(FileSystemLoader(str(SHARED_TEMPLATES_DIR)))
    return ChoiceLoader(loaders)


templates = Jinja2Templates(directory=str(SHARED_TEMPLATES_DIR))
templates.env.loader = _build_loader()


def _initials(name: str) -> str:
    """A user nevéből kétbetűs iniciálé. Pl. 'Hajas Gábor' → 'HG'."""
    parts = (name or "").strip().split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


_HU_WEEKDAYS = ("Hétfő", "Kedd", "Szerda", "Csütörtök", "Péntek", "Szombat", "Vasárnap")
_HU_MONTHS_SHORT = (
    "jan",
    "feb",
    "márc",
    "ápr",
    "máj",
    "jún",
    "júl",
    "aug",
    "szept",
    "okt",
    "nov",
    "dec",
)


def _hu_date(value, fmt: str = "long") -> str:
    """Magyar dátum-formatter Jinja-filterként.

    `fmt="long"` → `2026. 05. 03. · Vasárnap · KW18`
    `fmt="short"` → `2026.05.03.`
    `fmt="time"` → `2026.05.03. 14:30`
    `fmt="rel"` → relatív magyarul (`ma 14:30`, `tegnap 10:00`, `2 napja`, ...)
    """
    if value is None:
        return ""
    if fmt == "long":
        weekday = _HU_WEEKDAYS[value.weekday()]
        kw = value.isocalendar().week
        return f"{value:%Y. %m. %d.} · {weekday} · KW{kw:02d}"
    if fmt == "short":
        return f"{value:%Y.%m.%d.}"
    if fmt == "time":
        return f"{value:%Y.%m.%d. %H:%M}"
    if fmt == "rel":
        from datetime import timedelta

        from app.shared.models import utcnow

        now = utcnow()
        delta: timedelta = now - value
        if delta.total_seconds() < 60:
            return "épp most"
        if delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() // 60)} perce"
        if value.date() == now.date():
            return f"ma {value:%H:%M}"
        if (now.date() - value.date()).days == 1:
            return f"tegnap {value:%H:%M}"
        if delta.days < 7:
            return f"{delta.days} napja"
        return f"{value:%Y.%m.%d.}"
    return f"{value:%Y-%m-%d %H:%M}"


def _status_hu(value: str) -> str:
    """Rendelő státusz angol enum → magyar UI-szöveg."""
    mapping = {
        "new": "új",
        "ordered": "megrendelve",
        "arrived": "megérkezett",
        "cancelled": "lezárt",
    }
    return mapping.get(value, value)


def _status_hu_class(value: str) -> str:
    """A `req-status-pill` CSS-modifier osztálya, mockup-szerinti névvel."""
    mapping = {
        "new": "uj",
        "ordered": "megrendelve",
        "arrived": "megerkezett",
        "cancelled": "lezart",
    }
    return mapping.get(value, value)


templates.env.filters["initials"] = _initials
templates.env.filters["hu_date"] = _hu_date
templates.env.filters["status_hu"] = _status_hu
templates.env.filters["status_hu_class"] = _status_hu_class
