"""Kartoteka produktów."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import services
from ..auth import admin_user, current_user
from ..db import get_db
from ..models import ProductModel, Purchase, PurchaseItem, User, Variant
from ..schemas import iso, item_out, variant_out

router = APIRouter(prefix="/api", tags=["produkty"])


class VariantPatch(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    ean: str | None = Field(default=None, max_length=32)
    sku: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=80)
    tax: str | None = None
    price_net: Decimal | None = Field(default=None, ge=0)
    fakturownia_product_id: str | None = Field(default=None, max_length=40)


@router.get("/lookup")
def lookup(ean: str, _: User = Depends(current_user), db: Session = Depends(get_db)):
    v = services.find_variant(db, ean)
    return {"found": bool(v), "variant": variant_out(v) if v else None}


@router.get("/products")
def list_products(q: str = "", limit: int = 200, _: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = (select(Variant).join(ProductModel)
            .order_by(ProductModel.name, Variant.size, Variant.color).limit(min(max(limit, 1), 1000)))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(ProductModel.name_key.like(like), Variant.ean.like(like),
                              func.lower(Variant.sku).like(like), func.lower(Variant.size).like(like)))
    return [variant_out(v) for v in db.scalars(stmt)]


@router.get("/models/names")
def model_names(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """Podpowiedzi nazw przy dodawaniu nowego produktu."""
    return list(db.scalars(select(ProductModel.name).order_by(ProductModel.name)))


@router.patch("/variants/{vid}")
def patch_variant(vid: int, body: VariantPatch, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Poprawki kartoteki – tylko administrator."""
    v = db.get(Variant, vid)
    if not v:
        raise HTTPException(404, "Brak produktu")
    data = body.model_dump(exclude_unset=True)
    new_name = " ".join((data.get("name") or "").split())
    if new_name and new_name != v.model.name:
        others = [x for x in v.model.variants if x.id != v.id]
        target = db.scalar(select(ProductModel).where(ProductModel.name_key == new_name.lower()))
        if others or target:  # zmiana nazwy jednego wariantu = przeniesienie do innego modelu
            v.model = services.get_or_create_model(db, new_name, data.get("tax") or v.tax)
        else:
            v.model.name, v.model.name_key = new_name, new_name.lower()
    if data.get("tax"):
        v.model.tax = services.parse_tax(data["tax"], v.tax)
    if data.get("ean"):
        v.ean = services.clean_ean(data["ean"])
    for k in ("sku", "size", "color"):
        if data.get(k) is not None:
            setattr(v, k, data[k].strip())
    if data.get("price_net") is not None:
        v.purchase_price_net = data["price_net"]
    if "fakturownia_product_id" in data:
        v.fakturownia_product_id = (data["fakturownia_product_id"] or "").strip() or None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Taki EAN lub SKU już jest w bazie") from None
    return variant_out(v)


@router.get("/variants/{vid}/history")
def variant_history(vid: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    """Wszystkie partie produktu – gdzie, kiedy, kto i za ile kupił."""
    items = db.scalars(select(PurchaseItem).join(Purchase)
                       .where(PurchaseItem.variant_id == vid, Purchase.status != "koszyk")
                       .order_by(Purchase.bought_at.desc()))
    return [{**item_out(i), "purchase_id": i.purchase_id, "source_name": i.purchase.source_name,
             "source_type": i.purchase.source_type, "user": i.purchase.user.name,
             "bought_at": iso(i.purchase.bought_at)} for i in items]
