from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.shared.config import PROJECT_ROOT, settings

# Az alembic.ini a repo gyökerében él. Production-ben /opt/hub/app/alembic.ini.
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.db_url,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _alembic_upgrade_head() -> None:
    """Programatikus `alembic upgrade head`. Idempotens — ha már a head-en
    vagyunk, no-op."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", settings.db_url)
    command.upgrade(cfg, "head")


def init_db() -> None:
    """DB mappa létrehozása + séma fel-migrálása head-re.

    Három eset:

    1. **Fresh install** (nincs DB-fájl, nincs tábla) → alembic mindent létrehoz.
    2. **Naprakész DB** (van `alembic_version` tábla) → upgrade head no-op,
       vagy lefuttatja a függő migrációkat.
    3. **Baseline-előtti DB** (vannak táblák, de nincs `alembic_version`) →
       hibával leáll. A prod admin egyszer le kell stampelnie a baseline-t.
    """
    from app.shared import models  # noqa: F401  (registers mappers)
    from app.shared.config import ensure_dirs

    ensure_dirs()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    has_alembic = "alembic_version" in tables
    has_other_tables = bool(tables - {"alembic_version"})

    if not has_alembic and has_other_tables:
        raise RuntimeError(
            "Az adatbázisban léteznek táblák, de nincs alembic_version — "
            "először baseline-elni kell. Egyszer futtasd:\n"
            f"  alembic -c {ALEMBIC_INI} stamp head\n"
            "Majd indítsd újra."
        )

    _alembic_upgrade_head()
