from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.models import User, UserSession, utcnow
from app.shared.security import generate_token, hash_token, verify_password

SESSION_COOKIE_NAME = "hub_session"


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.execute(
        select(User).where(User.email == email.lower().strip(), User.active.is_(True))
    ).scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utcnow()
    return user


def create_session(
    db: Session, user: User, *, user_agent: str | None = None, ip: str | None = None
) -> str:
    raw_token = generate_token(32)
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=utcnow() + timedelta(days=settings.session_lifetime_days),
        user_agent=(user_agent or "")[:500] or None,
        ip=ip,
    )
    db.add(session)
    db.flush()
    return raw_token


def find_session(db: Session, raw_token: str) -> UserSession | None:
    if not raw_token:
        return None
    sess = db.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(raw_token))
    ).scalar_one_or_none()
    if sess is None:
        return None
    if sess.expires_at <= utcnow():
        db.delete(sess)
        return None
    sess.last_seen_at = utcnow()
    return sess


def destroy_session(db: Session, raw_token: str) -> None:
    sess = db.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(raw_token))
    ).scalar_one_or_none()
    if sess is not None:
        db.delete(sess)


def destroy_other_sessions(db: Session, user_id: int, except_session_id: int | None) -> int:
    """Törli a user összes sessionjét kivéve egyet (jellemzően a jelenlegit)."""
    stmt = select(UserSession).where(UserSession.user_id == user_id)
    if except_session_id is not None:
        stmt = stmt.where(UserSession.id != except_session_id)
    sessions = db.execute(stmt).scalars().all()
    for s in sessions:
        db.delete(s)
    return len(sessions)
