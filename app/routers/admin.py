"""Stan aplikacji, dziennik i ponawianie wysyłek do Fakturowni."""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import services
from ..auth import admin_user, current_user
from ..config import settings
from ..db import get_db
from ..models import Complaint, Purchase, Receipt, SyncLog, User, Variant, Writeoff

router = APIRouter(prefix="/api", tags=["administracja"])

PENDING = ("oczekuje", "blad")


@router.get("/status")
def status(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return {
        "fakturownia": {
            "enabled": settings.FAKTUROWNIA_ENABLED, "domain": settings.FAKTUROWNIA_DOMAIN,
            "warehouses": {"transit": settings.WAREHOUSE_TRANSIT_ID, "main": settings.WAREHOUSE_MAIN_ID,
                           "returns": settings.WAREHOUSE_RETURNS_ID},
        },
        "unsynced": {
            "pz": db.scalar(select(func.count(Purchase.id)).where(Purchase.status != "koszyk",
                                                                  Purchase.sync_status.in_(PENDING))),
            "mm": db.scalar(select(func.count(Receipt.id)).where(Receipt.status == "zatwierdzone",
                                                                 Receipt.sync_status.in_(PENDING))),
            "rw": db.scalar(select(func.count(Writeoff.id)).where(Writeoff.sync_status.in_(PENDING))),
        },
        "open_complaints": db.scalar(select(func.count(Complaint.id)).where(Complaint.status == "otwarta")),
        "products": db.scalar(select(func.count(Variant.id))),
        "environment": settings.APP_ENV,
    }


@router.get("/sync-log")
def sync_log(limit: int = 100, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(SyncLog).order_by(SyncLog.id.desc()).limit(min(max(limit, 1), 500)))
    return [{"id": s.id, "action": s.action, "ref": s.ref, "ok": s.ok, "message": s.message,
             "created_at": s.created_at.isoformat()} for s in rows]


@router.post("/sync/retry")
def sync_retry(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Przycisk „Wyślij ponownie teraz” w panelu administratora."""
    return services.retry_all(db)


@router.post("/internal/sync", include_in_schema=False)
def internal_sync(x_sync_token: str = Header(default=""), db: Session = Depends(get_db)):
    """Wywoływane co kilka minut przez Cloud Scheduler z nagłówkiem X-Sync-Token."""
    if not settings.SYNC_TOKEN or not hmac.compare_digest(x_sync_token, settings.SYNC_TOKEN):
        raise HTTPException(403, "Brak dostępu")
    return services.retry_all(db)
