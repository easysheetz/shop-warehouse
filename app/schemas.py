"""Zamiana obiektów z bazy na JSON dla aplikacji."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services
from .fakturownia import net_to_gross
from .models import Complaint, Purchase, PurchaseItem, Receipt, ReceiptLine, Variant


def money(x) -> str:
    return f"{Decimal(x or 0):.2f}"


def iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def variant_out(v: Variant) -> dict:
    return {
        "id": v.id, "model_id": v.model_id, "name": v.display_name, "model_name": v.model.name,
        "ean": v.ean, "sku": v.sku, "size": v.size, "color": v.color, "tax": v.tax, "brand": v.model.brand,
        "price_net": money(v.purchase_price_net), "price_gross": money(net_to_gross(v.purchase_price_net, v.tax)),
        "fakturownia_product_id": v.fakturownia_product_id,
        "created_by": v.created_by.name if v.created_by else "",
    }


def item_out(i: PurchaseItem) -> dict:
    return {
        "id": i.id, "variant": variant_out(i.variant), "qty": i.qty, "remaining": i.remaining,
        "received_qty": i.received_qty, "damaged_qty": i.damaged_qty, "written_off_qty": i.written_off_qty,
        "price_net": money(i.unit_price_net), "price_gross": money(net_to_gross(i.unit_price_net, i.tax)),
        "tax": i.tax, "is_new_product": i.is_new_product, "value_net": money(i.unit_price_net * i.qty),
        "value_gross": money(net_to_gross(i.unit_price_net, i.tax) * i.qty),
    }


def purchase_out(p: Purchase) -> dict:
    return {
        "id": p.id, "source_type": p.source_type, "source_name": p.source_name,
        "invoice_number": p.invoice_number, "note": p.note, "status": p.status, "target": p.target,
        "user": p.user.name, "created_at": iso(p.created_at), "bought_at": iso(p.bought_at),
        "sync_status": p.sync_status, "sync_error": p.sync_error, "fakt_doc_number": p.fakt_doc_number,
        "items": [item_out(i) for i in p.items],
        "total_qty": sum(i.qty for i in p.items), "remaining_qty": sum(i.remaining for i in p.items),
        "total_net": money(sum((Decimal(i.unit_price_net) * i.qty for i in p.items), Decimal(0))),
        "total_gross": money(sum((net_to_gross(i.unit_price_net, i.tax) * i.qty for i in p.items), Decimal(0))),
    }


def receipt_out(db: Session, r: Receipt) -> dict:
    lines = list(db.scalars(select(ReceiptLine).where(ReceiptLine.receipt_id == r.id).order_by(ReceiptLine.id.desc())))
    out = {
        "id": r.id, "status": r.status, "user": r.user.name, "created_at": iso(r.created_at),
        "confirmed_at": iso(r.confirmed_at), "confirmed_by": r.confirmed_by.name if r.confirmed_by else "",
        "sync_status": r.sync_status, "sync_error": r.sync_error,
        "mm_main_number": r.mm_main_number, "mm_returns_number": r.mm_returns_number,
        "lines": [{"id": ln.id, "variant": variant_out(ln.variant), "qty": ln.qty, "damaged": ln.damaged,
                   "note": ln.note} for ln in lines],
        "total_qty": sum(ln.qty for ln in lines),
    }
    if r.status == "otwarte":
        expected = services.expected_by_variant(db)
        scanned: dict[int, int] = {}
        for ln in lines:
            scanned[ln.variant_id] = scanned.get(ln.variant_id, 0) + ln.qty
        compare = []
        for vid in sorted(set(expected) | set(scanned)):
            v = db.get(Variant, vid)
            e, s = expected.get(vid, 0), scanned.get(vid, 0)
            compare.append({"variant": variant_out(v), "expected": e, "scanned": s, "diff": s - e,
                            "surplus_price_net": money(v.purchase_price_net) if s > e else None})
        compare.sort(key=lambda c: (c["diff"] == 0, c["variant"]["name"]))
        out["compare"] = compare
        out["missing_qty"] = sum(max(0, -c["diff"]) for c in compare)
        out["surplus_qty"] = sum(max(0, c["diff"]) for c in compare)
    return out


def complaint_out(c: Complaint) -> dict:
    p = c.item.purchase
    return {"id": c.id, "variant": variant_out(c.variant), "qty": c.qty, "note": c.note, "status": c.status,
            "resolution": c.resolution, "created_at": iso(c.created_at), "price_net": money(c.item.unit_price_net),
            "bought_by": p.user.name, "source_name": p.source_name, "bought_at": iso(p.bought_at),
            "invoice_number": p.invoice_number}
