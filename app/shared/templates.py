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
    """Status / event-action / Job-status angol enum → magyar UI-szöveg.

    Több modul státuszait egy filterben kezeli (overlap esetén a Rendelő
    státusza nyer, mert az volt először). A Munkák modul Job-státuszait
    a `STATUS_LABELS_HU` alapján fűzi be.
    """
    # Lazy import — a Jinja-filter elérhető legyen mielőtt a Munkák modul
    # ténylegesen importálódna (pl. CLI vagy migrációs script futtatáskor)
    try:
        from app.modules.jobs.services import STATUS_LABELS_HU

        job_labels = STATUS_LABELS_HU
    except ImportError:
        job_labels = {}

    mapping = {
        # Rendelő status
        "new": "új",
        "ordered": "megrendelve",
        "arrived": "megérkezett",
        "cancelled": "lezárt",
        # Rendelő event-action
        "created": "felvett",
        "edited": "módosítva",
        "commented": "kommentelt",
        "reassigned": "átadva",
        # Munkák Job-status (a `STATUS_LABELS_HU`-ból mergelve)
        **job_labels,
    }
    return mapping.get(value, value)


def _status_hu_class(value: str) -> str:
    """A `req-status-pill` és `status-pill` CSS-modifier osztálya."""
    try:
        from app.modules.jobs.services import STATUS_CLASS

        job_classes = STATUS_CLASS
    except ImportError:
        job_classes = {}

    mapping = {
        # Rendelő
        "new": "uj",
        "ordered": "megrendelve",
        "arrived": "megerkezett",
        "cancelled": "lezart",
        # Munkák (a CSS osztály-nevek a mockuphoz illeszkednek)
        **job_classes,
    }
    return mapping.get(value, value)


def _from_json(value):
    """JSON string → Python obj. A Rendelő Event payload-jához kell."""
    import json

    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


templates.env.filters["initials"] = _initials
templates.env.filters["hu_date"] = _hu_date
templates.env.filters["status_hu"] = _status_hu
templates.env.filters["status_hu_class"] = _status_hu_class
templates.env.filters["from_json"] = _from_json


def _now():
    """Jinja-global `now()` — naive UTC datetime. Pl. érvényesség
    ellenőrzéshez (`inv.expires_at <= now()`)."""
    from app.shared.models import utcnow

    return utcnow()


def _has_flag(obj, flag: str) -> bool:
    """`obj|has_flag("is_admin")` — dinamikus role-flag lekérdezés Jinja-ban.

    A `|attr(name)` szintaxis nem működik minden Jinja-verzióban, ezért
    ez a filter direkt `getattr`-rel olvas.
    """
    return bool(getattr(obj, flag, False))


_ROLE_SHORT = {
    "is_intake": "FELV",
    "is_designer": "GRAF",
    "is_workshop": "MŰH",
    "is_quote_handler": "ÁRA",
    "is_orderer": "REN",
    "is_admin": "ADM",
}


def _role_short(flag: str) -> str:
    """`flag|role_short` — `is_intake` → `FELV` stb. A user-card és az
    invite-lista role-dot rövidítései egységesen ide jönnek."""
    return _ROLE_SHORT.get(flag, flag.removeprefix("is_")[:4].upper())


_JOB_TYPE_LABELS = {
    "engraving": "Gravírozás",
    "sticker_matte": "Matt matrica",
    "sticker_gloss": "Fényes matrica",
    "sticker_clear": "Átlátszó matrica",
    "uv_print": "UV nyomtatás",
    "engraving_fiber": "Fiber gravír",
    "engraving_laser": "Lézer gravír",
    "heat_press": "Vasalás",
    "other": "Egyéb",
}


def _job_type_hu(value: str) -> str:
    """`Job.job_type` enum → magyar UI-szöveg."""
    return _JOB_TYPE_LABELS.get(str(value), str(value))


_TASK_TYPE_LABELS = {
    "uv_print": "UV nyomtatás",
    "co2_laser": "CO2 lézer",
    "fiber_laser": "Fiber lézer",
    "dtf_print": "DTF nyomtatás",
    "dtf_press": "DTF vasalás",
    "mug_press": "Bögre press",
    "engrave_manual": "Gravír (kézi)",
    "stamp": "Bélyegző",
    "business_card": "Névjegy",
    "sticker": "Matrica",
    "large_format": "Nagyformátum",
    "other": "Egyéb",
}


def _task_type_hu(value: str) -> str:
    """`JobTask.task_type` enum → magyar UI-szöveg."""
    return _TASK_TYPE_LABELS.get(str(value), str(value))


templates.env.globals["now"] = _now
templates.env.filters["has_flag"] = _has_flag
templates.env.filters["role_short"] = _role_short
templates.env.filters["job_type_hu"] = _job_type_hu
templates.env.filters["task_type_hu"] = _task_type_hu
