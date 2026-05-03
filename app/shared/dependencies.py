from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.shared.auth import SESSION_COOKIE_NAME, find_session
from app.shared.db import get_db
from app.shared.models import User, UserSession


class AuthRedirectError(Exception):
    """Raised when an unauthenticated user hits a page route — converted to a 303."""


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    sess = find_session(db, raw_token) if raw_token else None
    if sess is None or not sess.user.active:
        raise AuthRedirectError()
    return sess


def current_user(sess: UserSession = Depends(current_session)) -> User:
    return sess.user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin jog szükséges.")
    return user


def require_any_flag(*flags: str) -> Callable[[User], User]:
    """Dependency factory: a user-nek legalább egy flag-je legyen.

    Pl. `Depends(require_any_flag("is_designer", "is_intake"))` engedi a
    grafikust és a felvevőt is, de senki mást.

    Az admin mindig át megy.
    """

    def _dep(user: User = Depends(current_user)) -> User:
        if user.is_admin:
            return user
        if any(getattr(user, flag, False) for flag in flags):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nincs jogosultság.")

    return _dep


def auth_redirect_response() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
