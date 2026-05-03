from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: a könyvtár, amely az `app` package-et tartalmazza.
# config.py = .../app/shared/config.py → parents[2] = repo gyökér.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Production env fájl helye — a setup-app.sh ide rakja, és a systemd unit
# is innen olvas (EnvironmentFile=/opt/hub/.env).
PROD_ENV_FILE = "/opt/hub/.env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Több env fájl: a pydantic sorrendben tölti, a későbbi felülírja
        # a korábbit. Devben PROD_ENV_FILE nem létezik (silent skip), ekkor
        # a repo-szintű .env nyer. Productionben a PROD_ENV_FILE felülírja
        # a repo .env-et (ha esetleg van).
        env_file=(str(PROJECT_ROOT / ".env"), PROD_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    secret_key: str = "dev-only-change-me-in-production"
    base_url: str = "http://127.0.0.1:8080"
    secure_cookies: bool = False
    session_lifetime_days: int = 60

    # Adatbázis és storage
    database_url: str = "sqlite:///./data/hub.db"
    upload_dir: Path = PROJECT_ROOT / "uploads"
    corel_preview_dir: Path = PROJECT_ROOT / "test_previews"

    # Gemini (Fázis 4)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # IMAP poller (Fázis 4)
    imap_poll_interval_sec: int = 60

    # SMTP (Fázis 5)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    @property
    def db_url(self) -> str:
        return self.database_url

    @property
    def db_path(self) -> Path | None:
        """SQLite fájl path, ha sqlite:/// scheme; egyébként None."""
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.removeprefix("sqlite:///"))
        return None


settings = Settings()


def ensure_dirs() -> None:
    """Kötelező mappák létrehozása, ha hiányoznak.

    Explicit módon hívandó (NEM a modul betöltésekor), különben a Settings
    importja oldalkihatásként mkdir-t csinál — ami CLI-ből rossz cwd-ben
    rossz helyre próbálná, és permission error-ral elszállna.
    """
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.corel_preview_dir.mkdir(parents=True, exist_ok=True)
    db_path = settings.db_path
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
