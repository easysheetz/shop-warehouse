import threading
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

if settings.DATABASE_URL.startswith("sqlite"):
    engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    # stałe nazwy indeksów i ograniczeń – migracje Alembic są wtedy przewidywalne
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_local_lock = threading.Lock()
SYNC_LOCK_ID = 7_310_001  # dowolna stała – identyfikator blokady w PostgreSQL


@contextmanager
def sync_lock():
    """Jedna wysyłka do Fakturowni naraz – także między kilkoma instancjami w chmurze.

    Chroni przed podwójnym utworzeniem tego samego produktu lub dokumentu, gdy
    wysyłka z zatwierdzenia zakupu zbiegnie się z automatycznym ponawianiem.
    """
    with _local_lock:
        if engine.dialect.name != "postgresql":
            yield
            return
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": SYNC_LOCK_ID})
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SYNC_LOCK_ID})
                conn.commit()
