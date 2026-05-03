"""Sidebar navigációs struktúra.

A `hub_mockup.html` szerinti pontos felépítés: 4 szekció (Munkák,
Rendelő, Készlet, Adatok), mindegyik alatt nav-itemek SVG ikonnal,
opcionális badge-dzsel.

Csak azok a nav-itemek jelennek meg, amelyekhez a user role-flag-je
hozzáférést ad. A badge-ek értékét futás-időben számoljuk
(csak a Rendelő-é valós, a többi most None vagy 0).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.shared.models import User

# SVG-ikonok inline — a mockup-ból kiemelve. A template `safe`-fel ágyazza
# be, így a `<svg>` markup közvetlenül megy a HTML-be.
_ICON_HOME = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>'
_ICON_FILE = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>'
_ICON_PLUS = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>'
_ICON_TOOL = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>'
_ICON_MAIL = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>'
_ICON_QUOTE = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
_ICON_CHECK = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2h11"/></svg>'
_ICON_BOX = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>'
_ICON_USERS = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>'
_ICON_SHEET = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>'
_ICON_USER_SETTINGS = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
_ICON_INVITE = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>'
_ICON_TAG = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>'
_ICON_CATALOG = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>'


@dataclass(frozen=True)
class NavItem:
    key: str  # belső azonosító az aktív állapot kiválasztásához
    label: str
    href: str
    icon: str  # inline SVG markup
    visible: Callable[[User], bool]
    badge_key: str | None = None  # ha van, a counts dict-ből olvas
    urgent: bool = False  # piros badge


@dataclass(frozen=True)
class NavSection:
    key: str
    label: str
    marker: str | None  # CSS class a kis színes négyzethez (module-jobs, ...)
    items: tuple[NavItem, ...]


# A belső, "absztrakt" sidebar struktúra. A view függvény ezt szabja
# `dict`-té a template-nek, az aktív item-et a route-ja alapján emeli ki.
NAV_SECTIONS: tuple[NavSection, ...] = (
    NavSection(
        key="jobs",
        label="Munkák",
        marker="module-jobs",
        items=(
            NavItem(
                key="jobs_own",
                label="Saját munkáim",
                href="/jobs",
                icon=_ICON_HOME,
                visible=lambda u: u.is_admin or u.is_designer or u.is_intake,
            ),
            NavItem(
                key="jobs_pool",
                label="Közös pool",
                href="/jobs?view=pool",
                icon=_ICON_FILE,
                visible=lambda u: u.is_admin or u.is_designer,
            ),
            NavItem(
                key="jobs_new",
                label="Új munka",
                href="/jobs/new",
                icon=_ICON_PLUS,
                visible=lambda u: u.is_admin or u.is_intake or u.is_designer,
            ),
            NavItem(
                key="jobs_workshop",
                label="Műhely",
                href="/jobs/workshop",
                icon=_ICON_TOOL,
                visible=lambda u: u.is_admin or u.is_workshop,
            ),
            NavItem(
                key="jobs_inbox",
                label="Bejövő posta",
                href="/jobs/inbox",
                icon=_ICON_MAIL,
                visible=lambda u: u.is_admin or u.is_designer,
            ),
            NavItem(
                key="jobs_quotes",
                label="Árajánlatok",
                href="/jobs/quotes",
                icon=_ICON_QUOTE,
                visible=lambda u: u.is_admin or u.is_quote_handler,
            ),
        ),
    ),
    NavSection(
        key="rendelo",
        label="Rendelő",
        marker="module-rendelo",
        items=(
            NavItem(
                key="rendelo_list",
                label="Igények",
                href="/rendelo",
                icon=_ICON_CHECK,
                visible=lambda u: u.is_admin or u.is_orderer or u.is_workshop or u.is_designer,
                badge_key="rendelo_open",
            ),
        ),
    ),
    NavSection(
        key="stock",
        label="Készlet",
        marker="module-stock",
        items=(
            NavItem(
                key="stock_list",
                label="Termékek",
                href="/stock",
                icon=_ICON_BOX,
                visible=lambda u: u.is_admin or u.is_workshop or u.is_orderer,
            ),
        ),
    ),
    NavSection(
        key="data",
        label="Adatok",
        marker=None,
        items=(
            NavItem(
                key="data_customers",
                label="Ügyfelek",
                href="/customers",
                icon=_ICON_USERS,
                visible=lambda u: u.is_admin or u.is_intake or u.is_quote_handler,
            ),
            NavItem(
                key="data_sheet",
                label="Munkalap",
                href="/sheet",
                icon=_ICON_SHEET,
                visible=lambda u: u.is_admin or u.is_designer or u.is_workshop,
            ),
        ),
    ),
    NavSection(
        key="admin",
        label="Admin",
        marker=None,
        items=(
            NavItem(
                key="admin_users",
                label="Userek",
                href="/admin/users",
                icon=_ICON_USER_SETTINGS,
                visible=lambda u: u.is_admin,
            ),
            NavItem(
                key="admin_invites",
                label="Meghívók",
                href="/admin/invites",
                icon=_ICON_INVITE,
                visible=lambda u: u.is_admin,
            ),
            NavItem(
                key="admin_email_accounts",
                label="Email fiókok",
                href="/admin/email-accounts",
                icon=_ICON_MAIL,
                visible=lambda u: u.is_admin,
            ),
            NavItem(
                key="admin_rendelo_categories",
                label="Kategóriák",
                href="/admin/rendelo/categories",
                icon=_ICON_TAG,
                visible=lambda u: u.is_admin,
            ),
            NavItem(
                key="admin_rendelo_items",
                label="Tételek",
                href="/admin/rendelo/items",
                icon=_ICON_CATALOG,
                visible=lambda u: u.is_admin,
            ),
        ),
    ),
)


def _compute_counts(db: Session) -> dict[str, int]:
    """A nav-item-ek badge-éhez gyűjt számokat. Most csak a Rendelő nyitott
    igényeinek darabszámát adja vissza — később egészül ki."""

    # A Rendelő nyitott igények — lazy-import, hogy körkörös import ne legyen
    from app.modules.rendelo.models import Request, RequestStatus

    rendelo_open = (
        db.execute(
            select(func.count())
            .select_from(Request)
            .where(Request.status.in_([RequestStatus.NEW, RequestStatus.ORDERED]))
        ).scalar()
        or 0
    )

    return {"rendelo_open": rendelo_open}


def sidebar_nav(db: Session, user: User, active_key: str | None = None) -> list[dict]:
    """A `_sidebar.html` által várt struktúra: list[{label, marker, items: [...]}].

    Csak a látható item-eket adja vissza, és csak azokat a section-öket,
    amikben legalább egy item látható.
    """
    counts = _compute_counts(db)

    sections: list[dict] = []
    for section in NAV_SECTIONS:
        visible_items = []
        for item in section.items:
            if not item.visible(user):
                continue
            badge = counts.get(item.badge_key) if item.badge_key else None
            visible_items.append(
                {
                    "key": item.key,
                    "label": item.label,
                    "href": item.href,
                    "icon": item.icon,
                    "badge": badge,
                    "urgent": item.urgent,
                    "active": item.key == active_key,
                }
            )
        if visible_items:
            sections.append(
                {
                    "key": section.key,
                    "label": section.label,
                    "marker": section.marker,
                    # `nav_items` és nem `items`, mert a Jinja-attribute lookup
                    # a Python `dict.items()` metódusát rangsorolja előbbre.
                    "nav_items": visible_items,
                }
            )
    return sections


def sidebar_context(db: Session, user: User, active_key: str | None = None) -> dict:
    """Egyetlen kontextus-dict, amit a view a base/app template-nek átad."""
    return {
        "nav": sidebar_nav(db, user, active_key),
        "active_nav_key": active_key,
    }
