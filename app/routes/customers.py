"""Ügyfél (Customer) CRUD route-ok.

A `customers` tábla közös, ezért nem modul-szintű, hanem globális
route. A Munkák modul tölti tartalommal, de egy későbbi printbt.hu
redesign is olvasna belőle (a README szerint).

Hozzáférés: `is_admin`, `is_intake`, `is_quote_handler` (lásd
`app.shared.sidebar.NAV_SECTIONS`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.shared.db import get_db
from app.shared.dependencies import current_user
from app.shared.models import Customer, CustomerType, LegalType, User
from app.shared.sidebar import sidebar_context
from app.shared.templates import templates

router = APIRouter(prefix="/customers", tags=["customers"])


def _require_customer_access(user: User) -> None:
    """A `customers`-hez férők: admin, intake, quote_handler, designer."""
    if not (user.is_admin or user.is_intake or user.is_quote_handler or user.is_designer):
        raise HTTPException(403, "Nincs ügyfél-kezelő jogod.")


@router.get("", response_class=HTMLResponse)
def customers_list(
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    q: str | None = Query(None, description="Keresés név / email / telefon szerint"),
    customer_type: str | None = Query(None),
) -> HTMLResponse:
    _require_customer_access(user)

    stmt = select(Customer).order_by(Customer.name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Customer.name.ilike(like), Customer.email.ilike(like), Customer.phone.ilike(like))
        )
    if customer_type in ("retail", "reseller"):
        stmt = stmt.where(Customer.customer_type == customer_type)

    customers = db.execute(stmt).scalars().all()

    return templates.TemplateResponse(
        request,
        "customers/list.html",
        {
            "user": user,
            "title": "Ügyfelek",
            "topbar_title": "Ügyfelek",
            "topbar_subtitle": "vásárlók és viszonteladók törzse",
            "customers": customers,
            "q": q or "",
            "customer_type_filter": customer_type,
            **sidebar_context(db, user, active_key="data_customers"),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def customers_new_form(
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    error: str | None = Query(None),
    next: str | None = Query(None, description="redirect target after save"),
    email: str | None = Query(None, description="prefill (pl. inbox-ból)"),
    name: str | None = Query(None, description="prefill (pl. inbox-ból)"),
) -> HTMLResponse:
    _require_customer_access(user)
    return templates.TemplateResponse(
        request,
        "customers/form.html",
        {
            "user": user,
            "title": "Új ügyfél",
            "topbar_title": "Új ügyfél",
            "customer": None,
            "error": error,
            "next_url": next,
            "prefill_email": (email or "").strip().lower(),
            "prefill_name": (name or "").strip(),
            **sidebar_context(db, user, active_key="data_customers"),
        },
    )


@router.post("/new")
def customers_new_submit(
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    legal_type: str = Form("individual"),
    tax_number: str | None = Form(None),
    customer_type: str = Form("retail"),
    discount_pct: str | None = Form(None),
    country: str = Form("Magyarország"),
    postal_code: str | None = Form(None),
    city: str | None = Form(None),
    address_line1: str | None = Form(None),
    address_line2: str | None = Form(None),
    notes: str | None = Form(None),
    next: str | None = Form(None),
) -> Response:
    _require_customer_access(user)

    name = (name or "").strip()
    if not name:
        return RedirectResponse(
            url="/customers/new?error=A+n%C3%A9v+k%C3%B6telez%C5%91", status_code=303
        )

    lt = LegalType.COMPANY if legal_type == "company" else LegalType.INDIVIDUAL
    ct = CustomerType.RESELLER if customer_type == "reseller" else CustomerType.RETAIL
    discount_val = int(discount_pct) if discount_pct and discount_pct.strip() else None

    if lt == LegalType.COMPANY and not (tax_number or "").strip():
        return RedirectResponse(
            url="/customers/new?error=C%C3%A9geknek+ad%C3%B3sz%C3%A1m+k%C3%B6telez%C5%91",
            status_code=303,
        )

    customer = Customer(
        name=name,
        email=(email or "").strip().lower() or None,
        phone=(phone or "").strip() or None,
        legal_type=lt,
        tax_number=(tax_number or "").strip() or None if lt == LegalType.COMPANY else None,
        customer_type=ct,
        discount_pct=discount_val if ct == CustomerType.RESELLER else None,
        country=(country or "Magyarország").strip() or "Magyarország",
        postal_code=(postal_code or "").strip() or None,
        city=(city or "").strip() or None,
        address_line1=(address_line1 or "").strip() or None,
        address_line2=(address_line2 or "").strip() or None,
        notes=(notes or "").strip() or None,
        created_by_id=user.id,
    )
    db.add(customer)
    db.commit()

    # Ha a /jobs/new flow-ból érkeztünk, vissza oda az új customer ID-jával.
    if next:
        sep = "&" if "?" in next else "?"
        return RedirectResponse(url=f"{next}{sep}customer_id={customer.id}", status_code=303)
    return RedirectResponse(url=f"/customers/{customer.id}", status_code=303)


@router.get("/{customer_id}", response_class=HTMLResponse)
def customers_detail(
    customer_id: int,
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _require_customer_access(user)

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Ügyfél nem található.")

    # Customer-hez tartozó Job-ok lekérése (ha a Munkák modul tábla már létezik).
    customer_jobs: list = []
    try:
        from app.modules.jobs.models import Job

        customer_jobs = list(
            db.execute(
                select(Job).where(Job.customer_id == customer.id).order_by(Job.created_at.desc())
            )
            .scalars()
            .all()
        )
    except ImportError:
        pass

    return templates.TemplateResponse(
        request,
        "customers/detail.html",
        {
            "user": user,
            "title": customer.name,
            "topbar_title": customer.name,
            "topbar_subtitle": "ügyfél részletek",
            "customer": customer,
            "customer_jobs": customer_jobs,
            **sidebar_context(db, user, active_key="data_customers"),
        },
    )


@router.post("/{customer_id}/update")
def customers_update(
    customer_id: int,
    request: FastAPIRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    legal_type: str = Form("individual"),
    tax_number: str | None = Form(None),
    customer_type: str = Form("retail"),
    discount_pct: str | None = Form(None),
    country: str = Form("Magyarország"),
    postal_code: str | None = Form(None),
    city: str | None = Form(None),
    address_line1: str | None = Form(None),
    address_line2: str | None = Form(None),
    notes: str | None = Form(None),
) -> Response:
    _require_customer_access(user)

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Ügyfél nem található.")

    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "A név kötelező.")

    lt = LegalType.COMPANY if legal_type == "company" else LegalType.INDIVIDUAL
    ct = CustomerType.RESELLER if customer_type == "reseller" else CustomerType.RETAIL
    discount_val = int(discount_pct) if discount_pct and discount_pct.strip() else None

    if lt == LegalType.COMPANY and not (tax_number or "").strip():
        raise HTTPException(400, "Cégeknek adószám kötelező.")

    customer.name = name
    customer.email = (email or "").strip().lower() or None
    customer.phone = (phone or "").strip() or None
    customer.legal_type = lt
    customer.tax_number = (tax_number or "").strip() or None if lt == LegalType.COMPANY else None
    customer.customer_type = ct
    customer.discount_pct = discount_val if ct == CustomerType.RESELLER else None
    customer.country = (country or "Magyarország").strip() or "Magyarország"
    customer.postal_code = (postal_code or "").strip() or None
    customer.city = (city or "").strip() or None
    customer.address_line1 = (address_line1 or "").strip() or None
    customer.address_line2 = (address_line2 or "").strip() or None
    customer.notes = (notes or "").strip() or None

    db.commit()
    return RedirectResponse(url=f"/customers/{customer.id}", status_code=303)
