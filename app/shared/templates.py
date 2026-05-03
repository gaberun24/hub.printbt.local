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


templates.env.filters["initials"] = _initials
