"""Alembic env.py — a sqlalchemy URL-t a runtime felülírja a settings-ből.

Importáljuk a Hub modelljeit, hogy az autogenerate ismerje az összes
táblát.
"""

from __future__ import annotations

from sqlalchemy import engine_from_config, pool

from alembic import context

# Hub modellek importálása — regisztrálja a Base.metadata-t.
# Minden modul-saját modellt is importálni kell, hogy az autogenerate
# az ő tábláit is észlelje.
from app.modules.jobs import email_models  # noqa: F401
from app.modules.jobs import models as jobs_models  # noqa: F401
from app.modules.rendelo import models as rendelo_models  # noqa: F401
from app.shared import models  # noqa: F401
from app.shared.config import ensure_dirs, settings
from app.shared.db import Base

# A SQLite fájl szülő-mappája léteznie kell, mielőtt a connection nyit;
# autogenerate is connect-elne, ezért itt kell ensure_dirs.
ensure_dirs()

config = context.config

# A settings-ből vesszük a DB URL-t (egyetlen forrás), nem az alembic.ini-ből.
config.set_main_option("sqlalchemy.url", settings.db_url)

# A `fileConfig(config.config_file_name)` hívást SZÁNDÉKOSAN kihagyjuk:
# az alembic.ini [logger_*] szekciói átírják a root loggert WARN-ra,
# ami a hub.service és hub-worker.service Python logging-ját elnémítja
# az `init_db()` hívás után (mert az `command.upgrade` az env.py-t betölti
# minden indításkor). Hagyjuk hogy az app saját logging.basicConfig-ja
# érvényesüljön.

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
