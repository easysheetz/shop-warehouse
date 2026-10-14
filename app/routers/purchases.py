"""Zakupy w sklepie i dostawy – koszyk zapisywany na serwerze przy każdym skanie."""
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..auth import admin_user, current_user
from ..db import get_db
from ..models import Purchase, User
from ..schemas import money, purchase_out, variant_out

router = APIRouter(prefix="/api", tags=["zakupy"])


class CartIn(BaseModel):
    source_name: str = Field(default="", max_length=160)
    invoice_number: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=2000)


class NewProduct(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: str = Field(default="", max_length=40)
    color: str = Field(default="", max_length=80)


class ItemIn(BaseModel):
    ean: str = Field(max_length=32)
    qty: int = Field(default=1, ge=1, le=100000)
    price_net: str | float | None = None
    tax: str | None = None
    new_product: NewProduct | None = None


class BulkIn(BaseModel):
    items: list[ItemIn] = Field(max_length=2000)


class ItemPatch(BaseModel):
    qty: int | None = Field(default=None, ge=0, le=100000)
    price_net: str | float | None = None
    tax: str | None = None
    split_qty: int | None = Field(default=None, ge=1)


class WriteoffIn(BaseModel):
    qty: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=500)


def _check_kind(kind: str) -> str:
    if kind not in services.CART_KINDS:
        raise HTTPException(404, "Nieznany rodzaj zakupu")
    return kind


@router.get("/carts/{kind}")
def get_cart(kind: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Otwarty koszyk (zakup w sklepie albo dostawa) albo null."""
    p = services.get_open_cart(db, user, _check_kind(kind))
    return purchase_out(p) if p else None


@router.post("/carts/{kind}")
def start_cart(kind: str, body: CartIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = services.open_cart(db, user, _check_kind(kind), body.source_name, body.invoice_number, body.note)
    return purchase_out(p)


@router.patch("/purchases/{pid}")
def update_cart(pid: int, body: CartIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = services.lock_cart(db, pid, user)
    data = body.model_dump(exclude_unset=True)
    for k in ("source_name", "invoice_number", "note"):
        if k in data:
            setattr(p, k, data[k].strip())
    db.commit()
    return purchase_out(p)


@router.post("/purchases/{pid}/items")
def add_item(pid: int, body: ItemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Skan: dodaje 1 szt. (albo podaną ilość). Nieznany EAN → 404 z code=unknown_ean."""
    p = services.lock_cart(db, pid, user)
    item = services.add_item(db, p, user, body.ean, body.qty, body.price_net, body.tax,
                             body.new_product.model_dump() if body.new_product else None)
    db.refresh(p)
    return {"purchase": purchase_out(p), "item_id": item.id, "variant": variant_out(item.variant)}


@router.post("/purchases/{pid}/items/bulk")
def add_items_bulk(pid: int, body: BulkIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Wiele pozycji naraz (import CSV) – wszystko albo nic."""
    p = services.lock_cart(db, pid, user)
    errors = []
    for n, it in enumerate(body.items, 1):
        try:
            with db.begin_nested():
                services.add_item(db, p, user, it.ean, it.qty, it.price_net, it.tax,
                                  it.new_product.model_dump() if it.new_product else None, commit=False)
        except services.BusinessError as e:
            errors.append(f"pozycja {n} ({it.ean}): {e}")
    if errors:
        db.rollback()
        raise HTTPException(400, "Nic nie dodano. " + "; ".join(errors[:10]))
    db.commit()
    db.refresh(p)
    return purchase_out(p)


@router.patch("/purchases/{pid}/items/{iid}")
def patch_item(pid: int, iid: int, body: ItemPatch, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    p = services.lock_cart(db, pid, user)
    services.update_item(db, p, iid, body.qty, body.price_net, body.tax, body.split_qty)
    db.refresh(p)
    return purchase_out(p)


@router.delete("/purchases/{pid}")
def cancel_cart(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    services.cancel_cart(db, services.lock_cart(db, pid, user))
    return {"ok": True}


@router.post("/purchases/{pid}/finish")
def finish_cart(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Koniec zakupu: towar trafia do "W drodze", w Fakturowni powstaje PZ."""
    p = services.finish_cart(db, services.lock_cart(db, pid, user))
    db.refresh(p)
    return purchase_out(p)


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), _: User = Depends(current_user), db: Session = Depends(get_db)):
    """Podgląd pliku CSV – nic nie zapisuje."""
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(400, "Plik jest za duży (max 2 MB)")
    rows = services.parse_csv(db, services.decode_csv(raw))
    return {"rows": rows, "ok": sum(r["status"] != "blad" for r in rows),
            "errors": sum(r["status"] == "blad" for r in rows)}


@router.get("/in-transit")
def in_transit(_: User = Depends(current_user), db: Session = Depends(get_db)):
    purchases = list(db.scalars(select(Purchase).where(Purchase.status.in_(services.OPEN_PURCHASE_STATUSES),
                                                       Purchase.target == "transit")
                                .order_by(Purchase.bought_at.desc())))
    totals: dict[int, dict] = {}
    for it in services.in_transit_items(db):
        row = totals.setdefault(it.variant_id, {"variant": variant_out(it.variant), "qty": 0, "value_net": Decimal(0)})
        row["qty"] += it.remaining
        row["value_net"] += Decimal(it.unit_price_net) * it.remaining
    by_product = sorted(totals.values(), key=lambda r: r["variant"]["name"])
    total_value = sum((r["value_net"] for r in by_product), Decimal(0))
    for r in by_product:
        r["value_net"] = money(r["value_net"])
    return {"purchases": [purchase_out(p) for p in purchases], "by_product": by_product,
            "total_qty": sum(r["qty"] for r in by_product), "total_value_net": money(total_value)}


@router.get("/purchases")
def purchase_history(limit: int = 50, mine: bool = False, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    stmt = (select(Purchase).where(Purchase.status != "koszyk")
            .order_by(Purchase.bought_at.desc()).limit(min(max(limit, 1), 300)))
    if mine:
        stmt = stmt.where(Purchase.user_id == user.id)
    return [purchase_out(p) for p in db.scalars(stmt)]


@router.post("/items/{iid}/writeoff")
def writeoff(iid: int, body: WriteoffIn, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Odpis braku z "W drodze" (zgubione, sklep nie wydał) – dokument RW."""
    w = services.write_off(db, iid, body.qty, body.reason, user)
    return {"ok": True, "sync_status": w.sync_status, "sync_error": w.sync_error}
