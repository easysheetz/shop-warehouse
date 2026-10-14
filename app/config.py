"""Konfiguracja aplikacji – wyłącznie ze zmiennych środowiskowych.

Lokalnie zmienne czytane są z pliku `.env` (nie trafia do repozytorium).
W chmurze ustawia je pipeline wdrożenia z sekretów GitHuba.
Przy starcie `settings.validate()` zatrzymuje aplikację, jeśli w produkcji
brakuje sekretów albo zostały wartości domyślne.
"""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SECRET = "dev-only-secret-change-me"  # noqa: S105 – tylko lokalnie; produkcja go odrzuca


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    """Pusta zmienna (np. `SECRET_KEY=` w .env) = wartość domyślna."""
    return (os.getenv(name) or "").strip() or default


def _bool(name: str, default: bool = False) -> bool:
    return _env(name, str(default)).lower() in {"1", "true", "tak", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        # --- Aplikacja ---
        self.APP_ENV = _env("APP_ENV", "development")  # development / test / production
        self.DATABASE_URL = _env("DATABASE_URL", "postgresql+psycopg://skaner:skaner@localhost:5432/skaner")
        self.SECRET_KEY = _env("SECRET_KEY", DEFAULT_SECRET)
        self.SESSION_HOURS = int(_env("SESSION_HOURS", "720"))
        self.TIMEZONE = _env("TIMEZONE", "Europe/Warsaw")
        self.DEFAULT_TAX = _env("DEFAULT_TAX", "23")
        self.LOG_FORMAT = _env("LOG_FORMAT", "text")  # text / json (json = Google Cloud Logging)
        self.LOG_LEVEL = _env("LOG_LEVEL", "INFO")
        # Pierwsze konto administratora – tworzone tylko, gdy w bazie nie ma żadnego użytkownika
        self.ADMIN_NAME = _env("ADMIN_NAME", "Admin")
        self.ADMIN_PIN = _env("ADMIN_PIN")
        # Token, którym Cloud Scheduler wywołuje ponawianie wysyłek (/api/internal/sync)
        self.SYNC_TOKEN = _env("SYNC_TOKEN")

        # --- Fakturownia ---
        self.FAKTUROWNIA_ENABLED = _bool("FAKTUROWNIA_ENABLED", False)
        self.FAKTUROWNIA_DOMAIN = _env("FAKTUROWNIA_DOMAIN")  # "mojafirma" -> mojafirma.fakturownia.pl
        self.FAKTUROWNIA_TOKEN = _env("FAKTUROWNIA_TOKEN")
        self.FAKTUROWNIA_DEPARTMENT_ID = _env("FAKTUROWNIA_DEPARTMENT_ID")
        self.WAREHOUSE_TRANSIT_ID = _env("WAREHOUSE_TRANSIT_ID")   # 1. W drodze
        self.WAREHOUSE_MAIN_ID = _env("WAREHOUSE_MAIN_ID")         # 2. Główny (sprzedaż)
        self.WAREHOUSE_RETURNS_ID = _env("WAREHOUSE_RETURNS_ID")   # 3. Reklamacje
        self.FAKTUROWNIA_DEFAULT_SUPPLIER = _env("FAKTUROWNIA_DEFAULT_SUPPLIER", "Zakupy w sklepach stacjonarnych")
        self.FAKTUROWNIA_BASE_URL = _env("FAKTUROWNIA_BASE_URL")  # tylko do testów

    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.TIMEZONE)

    @property
    def fakturownia_url(self) -> str:
        if self.FAKTUROWNIA_BASE_URL:
            return self.FAKTUROWNIA_BASE_URL.rstrip("/")
        return f"https://{self.FAKTUROWNIA_DOMAIN}.fakturownia.pl"

    def warehouse_id(self, target: str) -> str:
        return {"transit": self.WAREHOUSE_TRANSIT_ID, "main": self.WAREHOUSE_MAIN_ID,
                "returns": self.WAREHOUSE_RETURNS_ID}[target]

    def problems(self) -> list[str]:
        """Lista błędów konfiguracji, które blokują start."""
        out: list[str] = []
        if self.APP_ENV not in {"development", "test", "production"}:
            out.append(f"APP_ENV: nieznana wartość '{self.APP_ENV}' (development / test / production)")
        if not self.DATABASE_URL.startswith(("postgresql", "sqlite")):
            out.append("DATABASE_URL: wymagany adres PostgreSQL (postgresql+psycopg://...)")
        try:
            ZoneInfo(self.TIMEZONE)
        except Exception:
            out.append(f"TIMEZONE: nieznana strefa '{self.TIMEZONE}'")
        if self.FAKTUROWNIA_ENABLED:
            for name in ("FAKTUROWNIA_TOKEN", "WAREHOUSE_TRANSIT_ID", "WAREHOUSE_MAIN_ID", "WAREHOUSE_RETURNS_ID"):
                if not getattr(self, name):
                    out.append(f"{name}: wymagane, gdy FAKTUROWNIA_ENABLED=true")
            if not (self.FAKTUROWNIA_DOMAIN or self.FAKTUROWNIA_BASE_URL):
                out.append("FAKTUROWNIA_DOMAIN: wymagane, gdy FAKTUROWNIA_ENABLED=true")
        if self.is_production:
            if self.SECRET_KEY == DEFAULT_SECRET or len(self.SECRET_KEY) < 32:
                out.append("SECRET_KEY: w produkcji wymagany losowy ciąg min. 32 znaków")
            if not self.DATABASE_URL.startswith("postgresql") or "skaner:skaner@localhost" in self.DATABASE_URL:
                out.append("DATABASE_URL: w produkcji wymagany adres produkcyjnej bazy PostgreSQL")
            if len(self.SYNC_TOKEN) < 32:
                out.append("SYNC_TOKEN: w produkcji wymagany losowy ciąg min. 32 znaków")
            if self.ADMIN_PIN in {"1234", "0000", "1111"}:
                out.append("ADMIN_PIN: nie używaj domyślnego/prostego PIN-u w produkcji")
        if self.ADMIN_PIN and not (self.ADMIN_PIN.isdigit() and 4 <= len(self.ADMIN_PIN) <= 12):
            out.append("ADMIN_PIN: 4–12 cyfr")
        return out

    def validate(self) -> None:
        problems = self.problems()
        if problems:
            raise RuntimeError("Błędna konfiguracja – aplikacja nie wystartuje:\n  - " + "\n  - ".join(problems))


settings = Settings()
