"""Skaner zakupów – API i serwowanie aplikacji (telefon + komputer).

Uruchomienie lokalnie:  docker compose up
Schemat bazy tworzą migracje (alembic upgrade head) – aplikacja sama nie zmienia tabel.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from .auth import hash_pin
from .config import settings
from .db import SessionLocal
from .logging_setup import setup_logging
from .models import User
from .routers import admin, catalog, purchases, receipts, users
from .services import BusinessError

STATIC = Path(__file__).resolve().parent.parent / "static"
log = logging.getLogger("skaner")


def ensure_first_admin() -> None:
    """Pierwsze konto administratora z ADMIN_NAME / ADMIN_PIN, gdy w bazie nie ma nikogo."""
    with SessionLocal() as db:
        if db.scalar(select(func.count(User.id))):
            return
        if not settings.ADMIN_PIN:
            log.warning("Brak użytkowników w bazie – ustaw ADMIN_PIN, żeby utworzyć konto administratora")
            return
        db.add(User(name=settings.ADMIN_NAME, pin_hash=hash_pin(settings.ADMIN_PIN), is_admin=True))
        db.commit()
        log.info("Utworzono konto administratora: %s", settings.ADMIN_NAME)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    settings.validate()
    ensure_first_admin()
    log.info("Start aplikacji (środowisko: %s, Fakturownia: %s)", settings.APP_ENV,
             "włączona" if settings.FAKTUROWNIA_ENABLED else "wyłączona")
    yield


app = FastAPI(title="Skaner zakupów", version="0.1.0", lifespan=lifespan,
              docs_url=None if settings.is_production else "/docs", redoc_url=None)

for r in (users.router, catalog.router, purchases.router, receipts.router, admin.router):
    app.include_router(r)


@app.exception_handler(BusinessError)
def business_error(_: Request, exc: BusinessError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": exc.code})


@app.middleware("http")
async def no_stale_files(request: Request, call_next):
    """Przeglądarka sprawdza przy każdym otwarciu, czy pliki aplikacji się zmieniły (ETag) –
    po wdrożeniu nowej wersji pracownicy od razu ją dostają."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/health", include_in_schema=False)
def health():
    """Sprawdzenie dla Cloud Run i pipeline'u wdrożenia: aplikacja działa i widzi bazę."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        log.exception("Health check: brak połączenia z bazą")
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})
    return {"status": "ok", "version": app.version}


# ------------------------------------------------------------------ aplikacja (front)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Wersja bez trybu offline: usuwa service workera zainstalowanego przez wcześniejszą wersję aplikacji.
    return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")
