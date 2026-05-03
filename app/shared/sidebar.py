"""Sidebar-context: a baloldali navigáció kontextusa.

A Hub sidebarja **modul-szintű** — a három modul (Munkák / Rendelő / Készlet)
megjelenítését a user role-flagjei vezérlik. Egy adott user csak azt látja,
amihez köze van. Az admin mindent.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.models import User


@dataclass(frozen=True)
class SidebarModule:
    """Egy modul-szintű menüpont a sidebarban."""

    key: str  # belső azonosító, az aktív modul kiemeléséhez
    label: str  # megjelenített név
    href: str  # base URL a modulhoz
    icon: str  # Unicode glyph (CSS-szel cserélhető SVG-re később)


# A modulok a megjelenítési sorrendben. Minden modulhoz egy `visible(user)`
# predikátum dönti el, hogy a sidebar mutassa-e az adott user-nek.
MODULES: list[tuple[SidebarModule, callable]] = [
    (
        SidebarModule(key="jobs", label="Munkák", href="/jobs", icon="🛠"),
        lambda u: u.is_admin or u.is_intake or u.is_designer or u.is_workshop or u.is_quote_handler,
    ),
    (
        SidebarModule(key="rendelo", label="Rendelő", href="/rendelo", icon="📦"),
        # A Rendelő modulhoz az is_orderer és az is_workshop is hozzáfér
        # (a műhelyes is felteszi az igényt amikor észreveszi hogy fogy).
        # A grafikus is láthatja, mert szintén feladhat igényt.
        lambda u: u.is_admin or u.is_orderer or u.is_workshop or u.is_designer,
    ),
    (
        SidebarModule(key="stock", label="Készlet", href="/stock", icon="📊"),
        lambda u: u.is_admin or u.is_workshop or u.is_orderer,
    ),
]


def visible_modules(user: User) -> list[SidebarModule]:
    return [mod for mod, predicate in MODULES if predicate(user)]


def sidebar_context(user: User, active_module: str | None = None) -> dict:
    """A base/app template által használt sidebar-context.

    Az `active_module` a jelenlegi route modulja (pl. `"rendelo"`), hogy
    a sidebarban kiemelhessük az aktív menüpontot.
    """
    return {
        "modules": visible_modules(user),
        "active_module": active_module,
    }
