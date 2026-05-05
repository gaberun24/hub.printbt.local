"""Malfini B2B API kliens — login + stock-availability lekérés.

A B2B API (default `https://api.malfini.com/api/v4`) authentikációt igényel:
egy felhasználói credential-pár jelszó-grant flow-val Bearer tokent kap, és
ezzel hívható a `/product/availabilities` (vagy a katalógus-egyéb endpointok).

A kliens szándékosan defenzív:
- A tényleges JSON séma több mezőnévvel is dolgozik (pl. `token` vagy
  `access_token`, `quantity` vagy `availableQuantity` stb.) — a Malfini
  API verziók közt változhat, és a swagger.json amivel dolgozunk
  nem 100%-ig naprakész.
- Minden hálózati hibát saját `MalfiniB2BError` exception-be csomagol,
  hogy a hívók egyetlen except-tel kezelhessék, és a kapott üzenetet az
  admin UI-on megmutathassuk.
- Stateless: nem cacheli a token-t state-ben — a hívó (a
  `app.modules.rendelo.malfini_stock`) tárolja a token-t a setting-táblában
  vagy a memóriában a refresh-cycle erejéig.

Elvárt válasz-sémák (tolerált variációk)
----------------------------------------
Login:
    POST /api-auth/login
    Body: {"username": "...", "password": "..."}
    Resp: {"token": "..."} | {"access_token": "..."} | {"jwt": "..."}

Availabilities:
    GET /product/availabilities
    Resp (Malfini tényleges formátum, 2026-05):
        [
          {"productSizeCode": "1000008", "quantity": 17,
           "date": "2026-05-04T00:00:00Z"},
          ...
        ]
    Más variánsok (defenzíven támogatott):
        {"items": [{"code": "...", "quantity": 42}, ...]}
        [{"code": "...", "availableQuantity": 42}, ...]
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_TIMEOUT = 30
DEFAULT_USER_AGENT = "hub-malfini-b2b/0.1 (https://printbt.hu)"


class MalfiniB2BError(Exception):
    """Bármilyen B2B API hiba — admin UI-n megjeleníthető üzenettel."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class LoginResult:
    token: str
    raw: dict


@dataclass
class StockEntry:
    code: str
    quantity: int


def _http_request(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict | list:
    """Minimális HTTP kliens urllib-bel. Saját exception-be csomagolja a hibákat."""
    headers = {
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
        **(headers or {}),
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — kontrollált URL
            raw = resp.read()
    except urllib.error.HTTPError as e:
        body_text = ""
        with contextlib.suppress(Exception):
            body_text = e.read().decode("utf-8", errors="replace")[:500]
        msg = f"HTTP {e.code} {e.reason}"
        if body_text:
            msg += f" — {body_text}"
        raise MalfiniB2BError(msg, status=e.code) from e
    except urllib.error.URLError as e:
        raise MalfiniB2BError(f"Hálózati hiba: {e.reason}") from e
    except TimeoutError as e:
        raise MalfiniB2BError(f"Timeout ({timeout}s)") from e

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise MalfiniB2BError(f"Érvénytelen JSON válasz: {e}") from e


def login(username: str, password: str, *, base_url: str) -> LoginResult:
    """B2B login → Bearer token.

    Több endpoint-variációt próbál (a swagger.json-ban `/api-auth/login`,
    de a Malfini API-k nem 100% konzisztensek minden környezetben).
    """
    if not username or not password:
        raise MalfiniB2BError("Hiányzó felhasználónév vagy jelszó")

    base = base_url.rstrip("/")
    candidates = [
        f"{base}/api-auth/login",
        f"{base}/auth/login",
        f"{base}/login",
    ]
    last_error: MalfiniB2BError | None = None
    for url in candidates:
        try:
            data = _http_request(
                url,
                method="POST",
                body={"username": username, "password": password},
            )
        except MalfiniB2BError as e:
            last_error = e
            # 404 → próbáljuk a következő endpoint-ot. Egyéb hiba → bukjuk.
            if e.status == 404:
                continue
            raise

        if not isinstance(data, dict):
            last_error = MalfiniB2BError(f"Váratlan login válasz típus: {type(data).__name__}")
            continue

        # Token kibányászása több névvel
        token = (
            data.get("token")
            or data.get("access_token")
            or data.get("accessToken")
            or data.get("jwt")
            or data.get("id_token")
        )
        if not token:
            last_error = MalfiniB2BError(f"Login válasz nem tartalmaz token-t: {list(data.keys())}")
            continue
        return LoginResult(token=str(token), raw=data)

    raise last_error or MalfiniB2BError("Nem sikerült login-olni egyik endpointra sem")


def fetch_availabilities(
    token: str, *, base_url: str, codes: list[str] | None = None
) -> list[StockEntry]:
    """Stock-adatok lekérése a B2B API-ról.

    Args:
        token: Bearer token a `login()`-ból
        base_url: pl. "https://api.malfini.com/api/v4"
        codes: opcionális kód-szűrő — csak lokálisan szűr a válaszra.
            (NEM küldjük az URL-ben query-paraméterben — 2000+ kód ~16 KB,
            ami nginx-default mögött 414-be fut. A B2B endpoint úgyis a
            teljes katalógust adja vissza, lokálisan szűrünk.)

    Returns:
        StockEntry lista. A `code` Malfini 7-jegyű kód, `quantity` darabszám.
    """
    base = base_url.rstrip("/")
    url = f"{base}/product/availabilities"

    data = _http_request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )

    # Több válasz-formát tolerálunk
    rows: list[dict] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("items", "availabilities", "data", "result", "products"):
            if key in data and isinstance(data[key], list):
                rows = data[key]
                break

    if not rows:
        return []

    out: list[StockEntry] = []
    code_filter = set(codes) if codes else None
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Kód több néven szerepelhet — Malfini-nál `productSizeCode`
        code = (
            row.get("productSizeCode")
            or row.get("code")
            or row.get("itemCode")
            or row.get("productCode")
            or row.get("sku")
        )
        if not code:
            continue
        code = str(code).strip()
        if code_filter is not None and code not in code_filter:
            continue
        # Mennyiség több néven szerepelhet, és lehet hogy floats jönnek
        qty_raw = (
            row.get("quantity")
            if "quantity" in row
            else row.get("availableQuantity")
            if "availableQuantity" in row
            else row.get("available")
            if "available" in row
            else row.get("stock")
            if "stock" in row
            else row.get("amount")
        )
        if qty_raw is None:
            continue
        try:
            qty = int(float(qty_raw))
        except (TypeError, ValueError):
            continue
        out.append(StockEntry(code=code, quantity=max(qty, 0)))

    return out


def fetch_availabilities_raw(token: str, *, base_url: str) -> tuple[int, str]:
    """Diagnosztikai: visszaadja a raw választ (HTTP status + body első ~3 KB-ja).

    A `fetch_availabilities()` parser-finomításához kell, ha az API
    formátuma nem stimmel a beépített tolerált variánsokkal.
    """
    base = base_url.rstrip("/")
    url = f"{base}/product/availabilities"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:  # noqa: S310
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        body = ""
        with contextlib.suppress(Exception):
            body = e.read().decode("utf-8", errors="replace")
        return e.code, body[:3000]
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}"

    text = raw.decode("utf-8", errors="replace")
    return status, text[:3000]


__all__ = [
    "MalfiniB2BError",
    "LoginResult",
    "StockEntry",
    "login",
    "fetch_availabilities",
    "fetch_availabilities_raw",
]
