"""Przyjęcie na magazyn i reklamacje."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..auth import admin_user, current_user
from ..db import get_db
from ..models import Complaint, Receipt, ReceiptLine, User, now
from ..schemas import complaint_out, receipt_out, variant_out

router = APIRouter(prefix="/api", tags=["przyjęcia"])


class ScanIn(BaseModel):
    ean: str = Field(max_length=32)
    qty: int = Field(default=1, ge=1, le=10000)
    damaged: bool = False
    note: str = Field(default="", max_length=2000)


class LinePatch(BaseModel):
    qty: int | None = Field(default=None, ge=0, le=10000)
    note: str | None = Field(default=None, max_length=2000)


class ComplaintClose(BaseModel):
    resolution: str = Field(min_length=2, max_length=1000)


@router.get("/receipts/current")
def current_receipt(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """Jedno wspólne otwarte przyjęcie – kilka osób może skanować jednocześnie."""
    r = db.scalar(select(Receipt).where(Receipt.status == "otwarte"))
    return receipt_out(db, r) if r else None


@router.post("/receipts")
def start_receipt(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return receipt_out(db, services.open_receipt(db, user))


@router.post("/receipts/{rid}/scan")
def receipt_scan(rid: int, body: ScanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = services.lock_open_receipt(db, rid)
    v = services.receipt_scan(db, r, user, body.ean, body.qty, body.damaged, body.note)
    expected = services.expected_by_variant(db).get(v.id, 0)
    scanned = sum(ln.qty for ln in db.scalars(select(ReceiptLine).where(ReceiptLine.receipt_id == r.id,
                                                                        ReceiptLine.variant_id == v.id)))
    return {"receipt": receipt_out(db, r), "last": {"variant": variant_out(v), "expected": expected,
                                                    "scanned": scanned}}


@router.patch("/receipts/{rid}/lines/{lid}")
def receipt_line_patch(rid: int, lid: int, body: LinePatch, _: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    r = services.lock_open_receipt(db, rid)
    ln = db.get(ReceiptLine, lid)
    if not ln or ln.receipt_id != r.id:
        raise HTTPException(404, "Brak pozycji")
    if body.qty == 0:
        db.delete(ln)
    else:
        if body.qty is not None:
            ln.qty = body.qty
        if body.note is not None and ln.damaged:
            ln.note = body.note.strip()
    db.commit()
    db.refresh(r)
    return receipt_out(db, r)


@router.post("/receipts/{rid}/confirm")
def receipt_confirm(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = services.lock_open_receipt(db, rid)
    services.confirm_receipt(db, r, user)
    db.refresh(r)
    return receipt_out(db, r)


@router.get("/receipts")
def receipt_history(limit: int = 30, _: User = Depends(current_user), db: Session = Depends(get_db)):
    rs = db.scalars(select(Receipt).where(Receipt.status == "zatwierdzone")
                    .order_by(Receipt.confirmed_at.desc()).limit(min(max(limit, 1), 200)))
    return [receipt_out(db, r) for r in rs]


@router.get("/complaints")
def complaints(status: str = "otwarta", _: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Complaint).where(Complaint.status == status).order_by(Complaint.created_at.desc()))
    return [complaint_out(c) for c in rows]


@router.post("/complaints/{cid}/close")
def complaint_close(cid: int, body: ComplaintClose, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    c = db.get(Complaint, cid)
    if not c:
        raise HTTPException(404, "Brak reklamacji")
    c.status, c.resolution, c.closed_at = "zamknieta", body.resolution, now()
    db.commit()
    return {"ok": True}
