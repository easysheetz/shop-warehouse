"""Wspólne przygotowanie testów.

Testy działają na osobnej bazie PostgreSQL (TEST_DATABASE_URL), którą czyszczą i odtwarzają
migracjami Alembic – tak samo jak w produkcji. Fakturownię udaje FakeFakturownia.
"""
import json
import os
from collections import defaultdict

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://skaner:skaner@localhost:5432/skaner_test")
os.environ["ADMIN_NAME"] = "Admin"
os.environ["ADMIN_PIN"] = "9999"
os.environ["SYNC_TOKEN"] = "test-sync-token"
os.environ["FAKTUROWNIA_ENABLED"] = "true"
os.environ["FAKTUROWNIA_TOKEN"] = "test-token"
os.environ["FAKTUROWNIA_BASE_URL"] = "https://fake.fakturownia.test"
os.environ["WAREHOUSE_TRANSIT_ID"] = "1"
os.environ["WAREHOUSE_MAIN_ID"] = "2"
os.environ["WAREHOUSE_RETURNS_ID"] = "3"

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import services  # noqa: E402
from app.fakturownia import FakturowniaClient  # noqa: E402


class FakeFakturownia:
    """Udaje Fakturownię: pamięta produkty, dokumenty i stany w magazynach."""

    def __init__(self):
        self.products, self.docs = {}, []
        self.stock = defaultdict(lambda: defaultdict(int))  # magazyn -> produkt -> ilość
        self.fail_next = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        assert body.get("api_token") == "test-token"
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(503, text="Serwis chwilowo niedostępny")
        if request.url.path == "/products.json":
            pid = str(1000 + len(self.products))
            self.products[pid] = body["product"]
            return httpx.Response(201, json={"id": int(pid), **body["product"]})
        if request.url.path == "/warehouse_documents.json":
            d = body["warehouse_document"]
            wh = d["warehouse_id"]
            for a in d["warehouse_actions"]:
                pid, q = str(a["product_id"]), a["quantity"]
                if d["kind"] == "pz":
                    self.stock[wh][pid] += q
                else:
                    if self.stock[wh][pid] < q:
                        return httpx.Response(422, json={"message": "brak towaru na magazynie"})
                    self.stock[wh][pid] -= q
                    if d["kind"] == "mm":
                        self.stock[a["warehouse2_id"]][pid] += q
            doc = {**d, "id": 500 + len(self.docs), "number": f"{d['kind'].upper()} {len(self.docs) + 1}/2026"}
            self.docs.append(doc)
            return httpx.Response(201, json=doc)
        return httpx.Response(404)

    def docs_of(self, kind):
        return [d for d in self.docs if d["kind"] == kind]


@pytest.fixture(scope="session", autouse=True)
def database():
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def fake():
    f = FakeFakturownia()
    services.get_fakturownia = lambda: FakturowniaClient(transport=httpx.MockTransport(f.handler))
    return f


@pytest.fixture(scope="session")
def client(fake):
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(client, name, pin):
    r = client.post("/api/login", json={"name": name, "pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return login(client, "Admin", "9999")


@pytest.fixture(scope="session")
def worker(client, admin):
    assert client.post("/api/users", json={"name": "Kuba", "pin": "1111"}, headers=admin).status_code == 200
    return login(client, "Kuba", "1111")


@pytest.fixture(scope="session")
def worker2(client, admin):
    assert client.post("/api/users", json={"name": "Ola", "pin": "2222"}, headers=admin).status_code == 200
    return login(client, "Ola", "2222")
