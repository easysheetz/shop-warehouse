"""Logika biznesowa.

Przepływ towaru:  koszyk zakupu (każdy skan od razu w bazie)
                  -> zakończenie zakupu: PZ do magazynu "W drodze"
                  -> przyjęcie: MM do "Główny" albo "Reklamacje" (FIFO, osobna linia na partię)
                  -> braki: odpis RW z "W drodze"
"""
import csv
import io
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import sync_lock
from .fakturownia import FakturowniaClient, FakturowniaError, batch_line
from .models import (
    Complaint,
    ProductModel,
    Purchase,
    PurchaseItem,
    Receipt,
    ReceiptAlloc,
    ReceiptLine,
    SyncLog,
    User,
    Variant,
    Writeoff,
    now,
)

log = logging.getLogger("skaner")

CART_KINDS = ("sklep", "dostawa")
OPEN_PURCHASE_STATUSES = ("w_drodze", "czesciowo")


class BusinessError(Exception):
    """Błąd do pokazania użytkownikowi. `code` pozwala frontendowi zareagować (np. nieznany EAN)."""

    def __init__(self, message: str, code: str = "", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def get_fakturownia() -> FakturowniaClient:
    return FakturowniaClient()


def add_log(db: Session, action: str, ref: str, ok: bool, message: str = "") -> None:
    db.add(SyncLog(action=action, ref=ref, ok=ok, message=message[:2000]))
    (log.info if ok else log.warning)("%s %s %s", action, ref, message[:300])


# ------------------------------------------------------------------ parsowanie danych
def clean_ean(ean) -> str:
    return "".join(ch for ch in str(ean or "") if ch.isalnum())


def parse_money(value) -> Decimal:
    if value is None or str(value).strip() == "":
        raise BusinessError("Brak ceny")
    try:
        d = Decimal(str(value).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise BusinessError(f"Zła cena: {value}") from None
    if d < 0 or d > Decimal("9999999"):
        raise BusinessError("Cena poza zakresem")
    return d.quantize(Decimal("0.01"))


def parse_tax(value, default: str) -> str:
    tax = str(value or "").strip().rstrip("%").lower() or default
    if tax not in {"23", "8", "5", "0", "zw", "np"}:
        raise BusinessError(f"Nieznana stawka VAT: {value}")
    return tax


# ------------------------------------------------------------------ kartoteka
def get_or_create_model(db: Session, name: str, tax: str, brand: str = "") -> ProductModel:
    clean = " ".join(name.split())
    key = clean.lower()
    m = db.scalar(select(ProductModel).where(ProductModel.name_key == key))
    if not m:
        m = ProductModel(name=clean, name_key=key, tax=tax, brand=brand)
        db.add(m)
        db.flush()
    return m


def unique_sku(db: Session, base: str) -> str:
    sku, n = base, 1
    while db.scalar(select(Variant.id).where(Variant.sku == sku)):
        n += 1
        sku = f"{base}-{n}"
    return sku


def create_variant(db: Session, ean: str, data: dict, price: Decimal, tax: str, user: User | None) -> Variant:
    name = " ".join(str(data.get("name") or "").split())
    if not name:
        raise BusinessError(f"EAN {ean}: podaj nazwę nowego produktu")
    model = get_or_create_model(db, name, tax, str(data.get("brand") or ""))
    v = Variant(
        model=model, ean=ean, sku=unique_sku(db, str(data.get("sku") or "").strip() or ean),
        size=str(data.get("size") or "").strip()[:40], color=str(data.get("color") or "").strip()[:80],
        purchase_price_net=price, created_by_id=user.id if user else None,
    )
    db.add(v)
    db.flush()
    return v


def find_variant(db: Session, ean: str) -> Variant | None:
    return db.scalar(select(Variant).where(Variant.ean == clean_ean(ean)))


# ------------------------------------------------------------------ koszyk (zakup w sklepie / dostawa)
def get_open_cart(db: Session, user: User, kind: str) -> Purchase | None:
    return db.scalar(select(Purchase).where(Purchase.user_id == user.id, Purchase.source_type == kind,
                                            Purchase.status == "koszyk"))


def open_cart(db: Session, user: User, kind: str, source_name: str = "", invoice_number: str = "",
              note: str = "") -> Purchase:
    if kind not in CART_KINDS:
        raise BusinessError("Nieznany rodzaj zakupu")
    existing = get_open_cart(db, user, kind)
    if existing:
        return existing
    if kind == "dostawa" and not source_name.strip():
        raise BusinessError("Podaj źródło dostawy (np. nazwę hurtowni)")
    p = Purchase(user_id=user.id, source_type=kind, source_name=source_name.strip()[:160],
                 invoice_number=invoice_number.strip()[:80], note=note, status="koszyk")
    db.add(p)
    try:
        db.commit()
    except IntegrityError:  # drugie kliknięcie w tej samej chwili
        db.rollback()
        p = get_open_cart(db, user, kind)
    return p


def lock_cart(db: Session, purchase_id: int, user: User) -> Purchase:
    """Pobiera koszyk z blokadą wiersza – dwa szybkie skany nie nadpiszą sobie ilości."""
    p = db.get(Purchase, purchase_id, with_for_update=True)
    if not p:
        raise BusinessError("Brak zakupu", status=404)
    if p.user_id != user.id and not user.is_admin:
        raise BusinessError("To nie Twój zakup", status=403)
    if p.status != "koszyk":
        raise BusinessError("Zakup jest już zakończony")
    return p


def add_item(db: Session, p: Purchase, user: User, ean: str, qty: int = 1, price_net=None, tax=None,
             new_product: dict | None = None, commit: bool = True) -> PurchaseItem:
    """Skan albo ręczne dodanie pozycji do koszyka. Zapisuje od razu (commit=False – przy imporcie CSV)."""
    ean = clean_ean(ean)
    if len(ean) < 4:
        raise BusinessError("Nieprawidłowy kod EAN")
    if not 1 <= int(qty) <= 100000:
        raise BusinessError("Ilość musi być od 1 do 100000")
    price = parse_money(price_net) if price_net not in (None, "") else None

    v = find_variant(db, ean)
    is_new = False
    if not v:
        if not new_product:
            raise BusinessError(f"Kodu {ean} nie ma w bazie – opisz nowy produkt", code="unknown_ean", status=404)
        if price is None:
            raise BusinessError("Podaj cenę zakupu netto nowego produktu")
        tax_new = parse_tax(tax, settings.DEFAULT_TAX)
        for _ in range(2):  # druga próba, gdy ktoś w tej samej chwili dodał ten EAN albo model
            try:
                with db.begin_nested():
                    v = create_variant(db, ean, new_product, price, tax_new, user)
                is_new = True
                break
            except IntegrityError:
                v = find_variant(db, ean)
                if v:
                    break
        if not v:
            raise BusinessError("Nie udało się dodać produktu – spróbuj ponownie")

    tax_v = parse_tax(tax, v.tax)
    last = next((i for i in reversed(p.items) if i.variant_id == v.id), None)
    if last and (price is None or price == last.unit_price_net) and tax_v == last.tax:
        last.qty += int(qty)
        item = last
    else:
        item = PurchaseItem(purchase=p, variant=v, qty=int(qty), tax=tax_v, is_new_product=is_new,
                            unit_price_net=price if price is not None else v.purchase_price_net)
        db.add(item)
    if price is not None:
        v.purchase_price_net = price  # system pamięta ostatnią cenę
    db.flush()
    if commit:
        db.commit()
    return item


def update_item(db: Session, p: Purchase, item_id: int, qty: int | None = None, price_net=None,
                tax=None, split_qty: int | None = None) -> None:
    """Zmiana ilości / ceny. split_qty < qty = nowa partia z nową ceną dla części sztuk."""
    item = next((i for i in p.items if i.id == item_id), None)
    if not item:
        raise BusinessError("Brak pozycji", status=404)
    if qty is not None:
        if qty < 0 or qty > 100000:
            raise BusinessError("Zła ilość")
        if qty == 0:
            p.items.remove(item)
            db.commit()
            return
        item.qty = qty
    if price_net not in (None, "") or tax not in (None, ""):
        price = parse_money(price_net) if price_net not in (None, "") else item.unit_price_net
        new_tax = parse_tax(tax, item.tax)
        if split_qty is not None and 1 <= split_qty < item.qty:
            item.qty -= split_qty
            db.add(PurchaseItem(purchase=p, variant=item.variant, qty=split_qty, unit_price_net=price,
                                tax=new_tax, is_new_product=item.is_new_product))
        elif split_qty is not None and split_qty != item.qty:
            raise BusinessError(f"Liczba sztuk z nową ceną: od 1 do {item.qty}")
        else:
            item.unit_price_net, item.tax = price, new_tax
        item.variant.purchase_price_net = price
    db.commit()


def cancel_cart(db: Session, p: Purchase) -> None:
    db.delete(p)
    db.commit()


def finish_cart(db: Session, p: Purchase) -> Purchase:
    if not p.items:
        raise BusinessError("Zakup jest pusty")
    p.status = "w_drodze"
    p.bought_at = now()
    db.commit()
    sync_purchase(db, p)
    return p


# ------------------------------------------------------------------ w drodze
def in_transit_items(db: Session, variant_id: int | None = None, lock: bool = False) -> list[PurchaseItem]:
    """Partie czekające w magazynie "W drodze" – najstarsze pierwsze (FIFO)."""
    stmt = (select(PurchaseItem).join(Purchase)
            .where(Purchase.status.in_(OPEN_PURCHASE_STATUSES), Purchase.target == "transit")
            .order_by(Purchase.bought_at, Purchase.id, PurchaseItem.id))
    if variant_id:
        stmt = stmt.where(PurchaseItem.variant_id == variant_id)
    if lock:
        stmt = stmt.with_for_update(of=PurchaseItem)
    return [it for it in db.scalars(stmt) if it.remaining > 0]


def expected_by_variant(db: Session) -> dict[int, int]:
    out: dict[int, int] = defaultdict(int)
    for it in in_transit_items(db):
        out[it.variant_id] += it.remaining
    return dict(out)


def refresh_purchase_status(p: Purchase) -> None:
    if p.target != "transit" or p.status == "koszyk":
        return
    if all(i.remaining == 0 for i in p.items):
        p.status = "zamkniety" if any(i.written_off_qty for i in p.items) else "przyjety"
    elif any(i.received_qty or i.damaged_qty or i.written_off_qty for i in p.items):
        p.status = "czesciowo"
    else:
        p.status = "w_drodze"


# ------------------------------------------------------------------ przyjęcie na magazyn
def open_receipt(db: Session, user: User) -> Receipt:
    r = db.scalar(select(Receipt).where(Receipt.status == "otwarte"))
    if r:
        return r
    r = Receipt(user_id=user.id)
    db.add(r)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        r = db.scalar(select(Receipt).where(Receipt.status == "otwarte"))
    return r


def lock_open_receipt(db: Session, receipt_id: int) -> Receipt:
    r = db.get(Receipt, receipt_id, with_for_update=True)
    if not r:
        raise BusinessError("Brak przyjęcia", status=404)
    if r.status != "otwarte":
        raise BusinessError("Przyjęcie jest już zatwierdzone")
    return r


def receipt_scan(db: Session, r: Receipt, user: User, ean: str, qty: int = 1, damaged: bool = False,
                 note: str = "") -> Variant:
    v = find_variant(db, ean)
    if not v:
        raise BusinessError("Nieznany kod – tego produktu nie ma w bazie", code="unknown_ean", status=404)
    if not 1 <= int(qty) <= 10000:
        raise BusinessError("Zła ilość")
    if damaged:
        if len(note.strip()) < 3:
            raise BusinessError("Opisz, co jest nie tak z produktem")
        db.add(ReceiptLine(receipt_id=r.id, variant_id=v.id, qty=qty, damaged=True, note=note.strip(),
                           scanned_by_id=user.id))
    else:
        ln = next((x for x in r.lines if x.variant_id == v.id and not x.damaged), None)
        if ln:
            ln.qty += qty
        else:
            db.add(ReceiptLine(receipt_id=r.id, variant_id=v.id, qty=qty, scanned_by_id=user.id))
    db.commit()
    return v


def confirm_receipt(db: Session, receipt: Receipt, user: User) -> Receipt:
    lines = [ln for ln in receipt.lines if ln.qty > 0]
    if not lines:
        raise BusinessError("Przyjęcie jest puste")

    # najpierw dobre sztuki, potem reklamacje – obie z najstarszych partii (FIFO)
    surplus: dict[bool, list] = defaultdict(list)
    for ln in sorted(lines, key=lambda x: (x.damaged, x.id)):
        left = ln.qty
        for it in in_transit_items(db, ln.variant_id, lock=True):
            if left <= 0:
                break
            take = min(it.remaining, left)
            if ln.damaged:
                it.damaged_qty += take
                db.add(Complaint(variant_id=ln.variant_id, purchase_item_id=it.id, receipt_id=receipt.id,
                                 qty=take, note=ln.note))
            else:
                it.received_qty += take
            db.add(ReceiptAlloc(receipt_id=receipt.id, purchase_item_id=it.id, qty=take, damaged=ln.damaged))
            db.flush()
            left -= take
        if left > 0:
            surplus[ln.damaged].append((ln, left))

    # nadwyżka: towar, którego nie było "w drodze" – PZ bezpośrednio na magazyn docelowy
    surplus_purchases = []
    for damaged, rows in surplus.items():
        sp = Purchase(user_id=user.id, source_type="nadwyzka", source_name=f"Nadwyżka przy przyjęciu #{receipt.id}",
                      target="returns" if damaged else "main", status="przyjety", receipt_id=receipt.id,
                      bought_at=now())
        db.add(sp)
        db.flush()
        for ln, q in rows:
            v = ln.variant
            it = PurchaseItem(purchase_id=sp.id, variant_id=v.id, qty=q, unit_price_net=v.purchase_price_net,
                              tax=v.tax, received_qty=0 if damaged else q, damaged_qty=q if damaged else 0)
            db.add(it)
            db.flush()
            if damaged:
                db.add(Complaint(variant_id=v.id, purchase_item_id=it.id, receipt_id=receipt.id, qty=q, note=ln.note))
        surplus_purchases.append(sp)

    touched = {db.get(PurchaseItem, a.purchase_item_id).purchase_id
               for a in db.scalars(select(ReceiptAlloc).where(ReceiptAlloc.receipt_id == receipt.id))}
    for pid in touched:
        refresh_purchase_status(db.get(Purchase, pid))

    receipt.status = "zatwierdzone"
    receipt.confirmed_at = now()
    receipt.confirmed_by_id = user.id
    db.commit()

    for sp in surplus_purchases:
        sync_purchase(db, sp)
    sync_receipt(db, receipt)
    return receipt


def write_off(db: Session, item_id: int, qty: int, reason: str, user: User) -> Writeoff:
    item = db.get(PurchaseItem, item_id, with_for_update=True)
    if not item or item.purchase.target != "transit" or item.purchase.status not in OPEN_PURCHASE_STATUSES:
        raise BusinessError("Brak partii w drodze", status=404)
    if qty < 1 or qty > item.remaining:
        raise BusinessError(f"Można odpisać od 1 do {item.remaining} szt.")
    item.written_off_qty += qty
    w = Writeoff(purchase_item_id=item.id, qty=qty, reason=reason, user_id=user.id)
    db.add(w)
    refresh_purchase_status(item.purchase)
    db.commit()
    sync_writeoff(db, w)
    return w


# ------------------------------------------------------------------ wysyłka do Fakturowni
def _disabled(db: Session, obj, label: str) -> bool:
    if settings.FAKTUROWNIA_ENABLED:
        return False
    if obj.sync_status != "wylaczone":
        obj.sync_status = "wylaczone"
        add_log(db, label, "", True, "Fakturownia wyłączona (FAKTUROWNIA_ENABLED=false) – tryb testowy")
        db.commit()
    return True


def _ensure_products(db: Session, fakt: FakturowniaClient, variants) -> None:
    for v in variants:
        db.refresh(v)
        if not v.fakturownia_product_id:
            v.fakturownia_product_id = fakt.create_product(v)
            add_log(db, "nowy produkt", v.sku, True, f"{v.display_name} → id {v.fakturownia_product_id}")
            db.commit()  # zapis od razu, żeby ponowienie nie zdublowało produktu


def _fail(db: Session, obj, label: str, err: Exception) -> None:
    db.rollback()
    obj.sync_status = "blad"
    obj.sync_error = str(err)
    add_log(db, label, "", False, str(err))
    db.commit()


def sync_purchase(db: Session, p: Purchase, fakt: FakturowniaClient | None = None) -> None:
    label = f"PZ zakup #{p.id}"
    with sync_lock():
        db.refresh(p)
        if p.status == "koszyk" or p.sync_status == "ok" or _disabled(db, p, label):
            return
        try:
            fakt = fakt or get_fakturownia()
            _ensure_products(db, fakt, [i.variant for i in p.items])
            if not p.fakt_doc_id:
                lines = [batch_line(i.variant.fakturownia_product_id, i.qty, i.unit_price_net, i.tax)
                         for i in p.items]
                supplier = p.source_name or settings.FAKTUROWNIA_DEFAULT_SUPPLIER
                doc = fakt.create_document("pz", settings.warehouse_id(p.target), lines, client_name=supplier,
                                           issue_date=p.bought_at.astimezone(settings.tz).date().isoformat())
                p.fakt_doc_id, p.fakt_doc_number = str(doc["id"]), str(doc.get("number") or "")
                db.commit()
            p.sync_status, p.sync_error = "ok", ""
            add_log(db, label, p.fakt_doc_number, True, f"{len(p.items)} partii, {sum(i.qty for i in p.items)} szt.")
            db.commit()
        except FakturowniaError as e:
            _fail(db, p, label, e)


def sync_receipt(db: Session, r: Receipt, fakt: FakturowniaClient | None = None) -> None:
    label = f"MM przyjęcie #{r.id}"
    with sync_lock():
        db.refresh(r)
        if r.status != "zatwierdzone" or r.sync_status == "ok" or _disabled(db, r, label):
            return
        allocs = list(db.scalars(select(ReceiptAlloc).where(ReceiptAlloc.receipt_id == r.id)))
        # MM można zrobić dopiero, gdy PZ do "W drodze" jest już w Fakturowni
        waiting = sorted({a.item.purchase_id for a in allocs if a.item.purchase.sync_status != "ok"})
        if waiting:
            r.sync_status = "oczekuje"
            r.sync_error = "Czeka na PZ zakupów: " + ", ".join(f"#{pid}" for pid in waiting)
            db.commit()
            return
        try:
            fakt = fakt or get_fakturownia()
            groups: dict[bool, dict[int, int]] = {False: defaultdict(int), True: defaultdict(int)}
            for a in allocs:
                groups[a.damaged][a.purchase_item_id] += a.qty
            for damaged, attr in ((False, "mm_main"), (True, "mm_returns")):
                if not groups[damaged] or getattr(r, f"{attr}_id"):
                    continue
                target = settings.warehouse_id("returns" if damaged else "main")
                lines = []
                for item_id, qty in groups[damaged].items():
                    it = db.get(PurchaseItem, item_id)
                    line = batch_line(it.variant.fakturownia_product_id, qty, it.unit_price_net, it.tax)
                    line["warehouse2_id"] = target
                    lines.append(line)
                doc = fakt.create_document("mm", settings.WAREHOUSE_TRANSIT_ID, lines)
                setattr(r, f"{attr}_id", str(doc["id"]))
                setattr(r, f"{attr}_number", str(doc.get("number") or ""))
                db.commit()
                add_log(db, label, str(doc.get("number") or ""), True,
                        f"MM → {'Reklamacje' if damaged else 'Główny'}: {sum(groups[damaged].values())} szt.")
            r.sync_status, r.sync_error = "ok", ""
            db.commit()
        except FakturowniaError as e:
            _fail(db, r, label, e)


def sync_writeoff(db: Session, w: Writeoff, fakt: FakturowniaClient | None = None) -> None:
    label = f"RW odpis #{w.id}"
    with sync_lock():
        db.refresh(w)
        if w.sync_status == "ok" or _disabled(db, w, label):
            return
        if w.item.purchase.sync_status != "ok":
            w.sync_status, w.sync_error = "oczekuje", f"Czeka na PZ zakupu #{w.item.purchase_id}"
            db.commit()
            return
        try:
            fakt = fakt or get_fakturownia()
            it = w.item
            doc = fakt.create_document("rw", settings.WAREHOUSE_TRANSIT_ID,
                                       [batch_line(it.variant.fakturownia_product_id, w.qty, it.unit_price_net,
                                                   it.tax)])
            w.fakt_doc_id, w.fakt_doc_number = str(doc["id"]), str(doc.get("number") or "")
            w.sync_status, w.sync_error = "ok", ""
            add_log(db, label, w.fakt_doc_number, True, f"RW {w.qty} szt. – {w.reason}")
            db.commit()
        except FakturowniaError as e:
            _fail(db, w, label, e)


def retry_all(db: Session) -> dict:
    """Ponawia wszystko, co nie dotarło do Fakturowni (kolejność: PZ, potem MM i RW).

    Wywoływane przez Cloud Scheduler (/api/internal/sync) albo przyciskiem w panelu admina.
    """
    if not settings.FAKTUROWNIA_ENABLED:
        return {"pz": 0, "mm": 0, "rw": 0}
    fakt = get_fakturownia()
    pending = ("oczekuje", "blad")
    ps = list(db.scalars(select(Purchase).where(Purchase.status != "koszyk", Purchase.sync_status.in_(pending))
                         .order_by(Purchase.id)))
    for p in ps:
        sync_purchase(db, p, fakt)
    rs = list(db.scalars(select(Receipt).where(Receipt.status == "zatwierdzone", Receipt.sync_status.in_(pending))
                         .order_by(Receipt.id)))
    for r in rs:
        sync_receipt(db, r, fakt)
    ws = list(db.scalars(select(Writeoff).where(Writeoff.sync_status.in_(pending)).order_by(Writeoff.id)))
    for w in ws:
        sync_writeoff(db, w, fakt)
    return {"pz": len(ps), "mm": len(rs), "rw": len(ws)}


# ------------------------------------------------------------------ import CSV
CSV_ALIASES = {
    "ean": "ean", "kod": "ean", "kod_ean": "ean", "barcode": "ean",
    "nazwa": "name", "name": "name", "produkt": "name",
    "rozmiar": "size", "size": "size",
    "kolor": "color", "color": "color",
    "ilosc": "qty", "ilość": "qty", "qty": "qty", "ilosc_szt": "qty", "szt": "qty",
    "cena_netto": "price_net", "cena": "price_net", "price_net": "price_net", "netto": "price_net",
    "vat": "tax", "stawka_vat": "tax", "tax": "tax",
}


def decode_csv(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def parse_csv(db: Session, text_data: str) -> list[dict]:
    """Ocenia wiersze pliku: znany produkt / nowy / błąd. Nic nie zapisuje."""
    sample = text_data[:2000]
    delimiter = max((";", ",", "\t"), key=sample.count)
    rows = [r for r in csv.reader(io.StringIO(text_data), delimiter=delimiter) if any(c.strip() for c in r)]
    if not rows:
        raise BusinessError("Plik jest pusty")
    header = [CSV_ALIASES.get(h.strip().lower().replace(" ", "_"), "") for h in rows[0]]
    if "ean" not in header or "qty" not in header:
        raise BusinessError("Brak wymaganych kolumn: ean i ilosc (pierwszy wiersz to nagłówki)")
    if len(rows) > 2001:
        raise BusinessError("Za dużo wierszy (maks. 2000)")

    out, seen_new = [], set()
    for n, r in enumerate(rows[1:], 2):
        rec = {k: (r[i].strip() if i < len(r) else "") for i, k in enumerate(header) if k}
        row = {"line": n, "ean": clean_ean(rec.get("ean", "")), "name": rec.get("name", ""),
               "size": rec.get("size", ""), "color": rec.get("color", ""), "tax": rec.get("tax", "").rstrip("%"),
               "qty": None, "price_net": None, "status": "", "errors": []}
        if len(row["ean"]) < 4:
            row["errors"].append("zły EAN")
        try:
            row["qty"] = int(Decimal(rec.get("qty", "").replace(",", ".")))
            if row["qty"] < 1:
                raise ValueError
        except (InvalidOperation, ValueError):
            row["errors"].append("zła ilość")
        v = find_variant(db, row["ean"]) if row["ean"] else None
        try:
            if rec.get("price_net"):
                row["price_net"] = str(parse_money(rec["price_net"]))
            elif v:
                row["price_net"] = str(v.purchase_price_net)
            else:
                row["errors"].append("brak ceny")
        except BusinessError as e:
            row["errors"].append(str(e).lower())
        try:
            row["tax"] = parse_tax(row["tax"], v.tax if v else settings.DEFAULT_TAX)
        except BusinessError as e:
            row["errors"].append(str(e).lower())
        if v:
            row["status"], row["known_name"] = "znany", v.display_name
        else:
            row["status"] = "nowy"
            if not row["name"] and row["ean"] not in seen_new:
                row["errors"].append("nowy produkt – brak nazwy")
            seen_new.add(row["ean"])
        if row["errors"]:
            row["status"] = "blad"
        out.append(row)
    return out
