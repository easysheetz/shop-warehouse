"""Cały proces: koszyk na serwerze -> PZ -> przyjęcie (MM, reklamacje, nadwyżki) -> odpisy (RW)."""
from datetime import UTC, datetime

from app.db import SessionLocal
from app.models import Purchase

EAN_M, EAN_L, EAN_CAP = "5900000000011", "5900000000012", "5900000000099"


def start(client, h, kind="sklep", **body):
    r = client.post(f"/api/carts/{kind}", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def add(client, h, pid, ean, expect=200, **body):
    r = client.post(f"/api/purchases/{pid}/items", json={"ean": ean, **body}, headers=h)
    assert r.status_code == expect, r.text
    return r.json()


def finish(client, h, pid):
    r = client.post(f"/api/purchases/{pid}/finish", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_cart_is_saved_on_server_after_each_scan(client, worker, fake):
    cart = start(client, worker, source_name="Sklep A")
    assert start(client, worker)["id"] == cart["id"]  # jeden otwarty koszyk na osobę

    # nieznany EAN – frontend dostaje kod i pokazuje formularz nowego produktu
    r = client.post(f"/api/purchases/{cart['id']}/items", json={"ean": EAN_M}, headers=worker)
    assert r.status_code == 404 and r.json()["code"] == "unknown_ean"

    add(client, worker, cart["id"], EAN_M, price_net="49,00",
        new_product={"name": "Bluza Nike Club", "size": "M", "color": "czarny"})
    add(client, worker, cart["id"], EAN_M)
    add(client, worker, cart["id"], EAN_M)

    # „przeładowanie strony” – koszyk jest w bazie, nie w telefonie
    saved = client.get("/api/carts/sklep", headers=worker).json()
    assert len(saved["items"]) == 1 and saved["items"][0]["qty"] == 3
    assert saved["items"][0]["is_new_product"] and saved["total_net"] == "147.00"

    done = finish(client, worker, cart["id"])
    assert done["status"] == "w_drodze" and done["sync_status"] == "ok"
    assert done["fakt_doc_number"].startswith("PZ")
    assert client.get("/api/carts/sklep", headers=worker).json() is None
    pz = fake.docs_of("pz")[-1]
    assert pz["warehouse_id"] == "1" and pz["client_name"] == "Sklep A"
    assert [(a["quantity"], a["purchase_price_net"]) for a in pz["warehouse_actions"]] == [(3, "49.00")]


def test_price_split_creates_separate_batches(client, worker, fake):
    cart = start(client, worker, source_name="Sklep B")
    add(client, worker, cart["id"], EAN_M, qty=2, price_net="39")
    add(client, worker, cart["id"], EAN_L, qty=2, price_net="39",
        new_product={"name": "bluza nike  CLUB", "size": "L", "color": "czarny"})  # ten sam model
    res = add(client, worker, cart["id"], EAN_L)
    item_l = next(i for i in res["purchase"]["items"] if i["variant"]["ean"] == EAN_L)
    assert item_l["qty"] == 3

    # 1 z 3 sztuk tańsza → osobna partia
    r = client.patch(f"/api/purchases/{cart['id']}/items/{item_l['id']}",
                     json={"price_net": "35", "split_qty": 1}, headers=worker)
    assert r.status_code == 200
    lines = sorted((i["variant"]["ean"], i["qty"], i["price_net"]) for i in r.json()["items"])
    assert lines == [(EAN_M, 2, "39.00"), (EAN_L, 1, "35.00"), (EAN_L, 2, "39.00")]

    finish(client, worker, cart["id"])
    assert len(fake.products) == 2  # produkty w Fakturowni zakładane raz
    pz = fake.docs_of("pz")[-1]
    assert sorted(a["purchase_price_net"] for a in pz["warehouse_actions"]) == ["35.00", "39.00", "39.00"]

    products = client.get("/api/products", headers=worker).json()
    assert len({p["model_id"] for p in products}) == 1
    m = next(p for p in products if p["ean"] == EAN_M)
    assert m["price_net"] == "39.00" and m["price_gross"] == "47.97"  # system pamięta ostatnią cenę

    transit = client.get("/api/in-transit", headers=worker).json()
    assert transit["total_qty"] == 3 + 2 + 3
    assert transit["total_value_net"] == f"{3 * 49 + 2 * 39 + 2 * 39 + 35:.2f}"


def test_cart_belongs_to_its_owner(client, worker, worker2):
    cart = start(client, worker, source_name="Sklep C")
    r = client.post(f"/api/purchases/{cart['id']}/items", json={"ean": EAN_M}, headers=worker2)
    assert r.status_code == 403
    # ten sam nowy EAN opisany „jednocześnie” przez drugą osobę – używany jest istniejący produkt
    other = start(client, worker2, source_name="Sklep D")
    res = add(client, worker2, other["id"], EAN_M, price_net="50", new_product={"name": "Inna nazwa"})
    assert res["variant"]["model_name"] == "Bluza Nike Club"
    assert client.delete(f"/api/purchases/{other['id']}", headers=worker2).status_code == 200
    assert client.delete(f"/api/purchases/{cart['id']}", headers=worker).status_code == 200


def test_receipt_with_complaint_and_surplus(client, worker, admin, fake):
    rid = client.post("/api/receipts", headers=worker).json()["id"]
    assert client.post("/api/receipts", headers=admin).json()["id"] == rid  # jedno wspólne przyjęcie
    for _ in range(4):
        client.post(f"/api/receipts/{rid}/scan", json={"ean": EAN_M}, headers=worker)
    bad = client.post(f"/api/receipts/{rid}/scan", json={"ean": EAN_M, "damaged": True}, headers=worker)
    assert bad.status_code == 400
    client.post(f"/api/receipts/{rid}/scan", headers=admin,
                json={"ean": EAN_M, "damaged": True, "note": "dziura na rękawie"})
    last = client.post(f"/api/receipts/{rid}/scan", json={"ean": EAN_L, "qty": 4}, headers=worker).json()
    assert last["last"]["expected"] == 3 and last["last"]["scanned"] == 4
    cur = client.get("/api/receipts/current", headers=worker).json()
    assert cur["surplus_qty"] == 1 and cur["missing_qty"] == 0

    done = client.post(f"/api/receipts/{rid}/confirm", headers=worker).json()
    assert done["status"] == "zatwierdzone" and done["sync_status"] == "ok"

    mm = fake.docs_of("mm")
    main = next(d for d in mm if d["warehouse_actions"][0]["warehouse2_id"] == "2")
    ret = next(d for d in mm if d["warehouse_actions"][0]["warehouse2_id"] == "3")
    m_lines = sorted((a["purchase_price_net"], a["quantity"]) for a in main["warehouse_actions"]
                     if a["product_id"] == "1000")
    assert m_lines == [("39.00", 1), ("49.00", 3)]  # FIFO, osobna linia dla każdej ceny
    assert [(a["purchase_price_net"], a["quantity"]) for a in ret["warehouse_actions"]] == [("39.00", 1)]
    surplus = [d for d in fake.docs_of("pz") if d["warehouse_id"] == "2"]
    assert len(surplus) == 1 and surplus[0]["warehouse_actions"][0]["quantity"] == 1

    assert fake.stock["1"]["1000"] == 0 and fake.stock["1"]["1001"] == 0
    assert fake.stock["2"]["1000"] == 4 and fake.stock["3"]["1000"] == 1 and fake.stock["2"]["1001"] == 4

    comp = client.get("/api/complaints", headers=worker).json()
    assert len(comp) == 1 and comp[0]["note"] == "dziura na rękawie" and comp[0]["bought_by"] == "Kuba"
    assert client.post(f"/api/complaints/{comp[0]['id']}/close", json={"resolution": "zwrot do sklepu"},
                       headers=worker).status_code == 403
    assert client.post(f"/api/complaints/{comp[0]['id']}/close", json={"resolution": "zwrot do sklepu"},
                       headers=admin).status_code == 200
    assert client.get("/api/in-transit", headers=worker).json()["total_qty"] == 0


def test_writeoff_creates_rw(client, worker, admin, fake):
    cart = start(client, worker, source_name="Sklep E")
    p = add(client, worker, cart["id"], EAN_M, qty=2, price_net="45")["purchase"]
    finish(client, worker, cart["id"])
    item_id = p["items"][0]["id"]
    assert client.post(f"/api/items/{item_id}/writeoff", json={"qty": 1, "reason": "x"},
                       headers=worker).status_code == 403
    r = client.post(f"/api/items/{item_id}/writeoff", json={"qty": 1, "reason": "sklep nie wydał"}, headers=admin)
    assert r.json()["sync_status"] == "ok"
    assert fake.docs_of("rw")[-1]["warehouse_actions"][0]["purchase_price_net"] == "45.00"
    assert client.get("/api/in-transit", headers=worker).json()["total_qty"] == 1


def test_fakturownia_down_then_scheduler_retry(client, worker, admin, fake):
    fake.fail_next = 1
    cart = start(client, worker, source_name="Sklep F")
    add(client, worker, cart["id"], EAN_L, price_net="40")
    assert finish(client, worker, cart["id"])["sync_status"] == "blad"

    rid = client.post("/api/receipts", headers=worker).json()["id"]
    client.post(f"/api/receipts/{rid}/scan", json={"ean": EAN_L}, headers=worker)
    client.post(f"/api/receipts/{rid}/scan", json={"ean": EAN_M}, headers=worker)
    r = client.post(f"/api/receipts/{rid}/confirm", headers=worker).json()
    assert r["sync_status"] == "oczekuje" and "Czeka na PZ" in r["sync_error"]
    assert client.get("/api/status", headers=admin).json()["unsynced"] == {"pz": 1, "mm": 1, "rw": 0}

    assert client.post("/api/internal/sync", headers={"X-Sync-Token": "zly"}).status_code == 403
    assert client.post("/api/internal/sync").status_code == 403
    assert client.post("/api/internal/sync", headers={"X-Sync-Token": "test-sync-token"}).status_code == 200
    assert client.get("/api/status", headers=admin).json()["unsynced"] == {"pz": 0, "mm": 0, "rw": 0}
    assert fake.stock["1"]["1001"] == 0 and fake.stock["1"]["1000"] == 0


def test_pz_date_uses_polish_time(client, worker, admin, fake):
    cart = start(client, worker, source_name="Sklep nocny")
    add(client, worker, cart["id"], EAN_M, price_net="49")
    finish(client, worker, cart["id"])
    with SessionLocal() as db:
        p = db.get(Purchase, cart["id"])
        p.bought_at = datetime(2026, 10, 12, 22, 30, tzinfo=UTC)  # 00:30 13.10 w Polsce (CEST)
        p.fakt_doc_id, p.sync_status = None, "blad"
        db.commit()
    client.post("/api/sync/retry", headers=admin)
    assert fake.docs_of("pz")[-1]["issue_date"] == "2026-10-13"


def test_csv_preview_and_all_or_nothing_import(client, worker):
    text = ("EAN;Nazwa;Rozmiar;Kolor;Ilość;Cena netto;VAT\n"
            f"{EAN_M};;;;2;41,50;23\n"
            f"{EAN_CAP};Czapka zimowa;uni;szara;5;12,00;23\n"
            "5900000000098;;;;1;10;23\n"
            "abc;Coś;;;x;;\n")
    files = {"file": ("dostawa.csv", text.encode("cp1250"), "text/csv")}
    prev = client.post("/api/import/csv", files=files, headers=worker).json()
    assert [r["status"] for r in prev["rows"]] == ["znany", "nowy", "blad", "blad"]

    cart = start(client, worker, kind="dostawa", source_name="Hurtownia X", invoice_number="FV 12/10/2026")
    bad = client.post(f"/api/purchases/{cart['id']}/items/bulk", headers=worker, json={"items": [
        {"ean": EAN_M, "qty": 2, "price_net": "41.50"},
        {"ean": "5900000000098", "qty": 1, "price_net": "10"},  # nowy bez opisu
    ]})
    assert bad.status_code == 400
    assert client.get("/api/carts/dostawa", headers=worker).json()["items"] == []  # nic nie dodano

    ok = client.post(f"/api/purchases/{cart['id']}/items/bulk", headers=worker, json={"items": [
        {"ean": EAN_M, "qty": 2, "price_net": "41.50"},
        {"ean": EAN_CAP, "qty": 5, "price_net": "12", "tax": "23",
         "new_product": {"name": "Czapka zimowa", "size": "uni", "color": "szara"}},
    ]})
    assert ok.status_code == 200 and ok.json()["total_qty"] == 7
    done = finish(client, worker, cart["id"])
    assert done["source_type"] == "dostawa" and done["invoice_number"] == "FV 12/10/2026"


def test_only_admin_edits_catalog(client, worker, admin):
    v = client.get(f"/api/products?q={EAN_CAP}", headers=worker).json()[0]
    assert client.patch(f"/api/variants/{v['id']}", json={"size": "L"}, headers=worker).status_code == 403
    r = client.patch(f"/api/variants/{v['id']}", json={"size": "one size", "price_net": "11.5"}, headers=admin)
    assert r.json()["size"] == "one size" and r.json()["price_net"] == "11.50"
    hist = client.get(f"/api/variants/{v['id']}/history", headers=worker).json()
    assert hist[0]["source_name"] == "Hurtownia X" and hist[0]["user"] == "Kuba"


def test_parallel_scans_do_not_lose_quantity(client, worker):
    """20 skanów wysłanych naraz (np. szybki czytnik) – żadna sztuka nie może zginąć."""
    from concurrent.futures import ThreadPoolExecutor

    ean = "5900000000777"
    cart = start(client, worker, source_name="Sklep równoległy")
    add(client, worker, cart["id"], ean, price_net="9.99", new_product={"name": "Skarpety", "size": "39-42"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _: client.post(f"/api/purchases/{cart['id']}/items",
                                                    json={"ean": ean}, headers=worker).status_code, range(20)))
    assert codes == [200] * 20
    items = client.get("/api/carts/sklep", headers=worker).json()["items"]
    assert len(items) == 1 and items[0]["qty"] == 21
    client.delete(f"/api/purchases/{cart['id']}", headers=worker)
