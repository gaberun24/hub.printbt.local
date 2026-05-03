"""FastAPI bootstrap — a Hub egész app belépési pontja.

Indítás dev-ben:
    uvicorn app.main:app --reload --port 8080
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.modules.rendelo.routes import admin as rendelo_admin
from app.modules.rendelo.routes import views as rendelo_views
from app.routes import admin, auth, views
from app.shared.config import ensure_dirs, settings
from app.shared.db import init_db
from app.shared.dependencies import AuthRedirectError, auth_redirect_response

STATIC_DIR = Path(__file__).parent / "static"

# A StaticFiles mount ellenőrzi a könyvtár létezését konstruktor-időben,
# ezért az ensure_dirs-nek a mount előtt kell futnia.
ensure_dirs()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Hub", version="0.1.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")


@app.exception_handler(AuthRedirectError)
async def _auth_redirect_handler(_request: Request, _exc: AuthRedirectError):
    return auth_redirect_response()


app.include_router(auth.router)
# Admin route-ok ELŐBB legyenek, mint a `/{request_id}` dynamikus path
# a `rendelo_views`-ban — különben pl. `/admin/rendelo/categories` `/{request_id}`
# alá esne és 404-et adna. A `rendelo_admin.router` saját prefixe `/admin/rendelo`,
# tehát nem ütközik, de az `admin.router` (`/admin`) sem.
app.include_router(admin.router)
app.include_router(rendelo_admin.router)
app.include_router(rendelo_views.router)
app.include_router(views.router)
