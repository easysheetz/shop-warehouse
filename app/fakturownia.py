"""Klient API Fakturowni – tylko to, czego potrzebuje skaner.

Dokumentacja: https://github.com/fakturownia/API
 - POST /products.json             – utworzenie produktu
 - POST /warehouse_documents.json  – dokumenty magazynowe PZ / MM / RW

Wszystkie dokumenty mają po jednej linii na PARTIĘ (ten sam produkt po innej
cenie = osobna linia), dzięki czemu wartość magazynu odpowiada rzeczywistym cenom.
"""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import httpx

from .config import settings


def local_today() -> str:
    """Dzisiejsza data w polskiej strefie czasowej (serwery w chmurze działają w UTC)."""
    return datetime.now(settings.tz).date().isoformat()


class FakturowniaError(Exception):
    pass


def net_to_gross(net, tax: str) -> Decimal:
    try:
        rate = Decimal(tax)
    except Exception:  # "zw", "np" itd.
        rate = Decimal(0)
    return (Decimal(net) * (1 + rate / 100)).quantize(Decimal("0.01"), ROUND_HALF_UP)


class FakturowniaClient:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.base = settings.fakturownia_url
        self.token = settings.FAKTUROWNIA_TOKEN
        self._client = httpx.Client(timeout=30, transport=transport)

    def _post(self, path: str, payload: dict) -> dict:
        body = {"api_token": self.token, **payload}
        try:
            r = self._client.post(f"{self.base}{path}", json=body, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise FakturowniaError(f"Brak połączenia z Fakturownią: {e}") from e
        if r.status_code >= 400:
            raise FakturowniaError(f"Fakturownia {r.status_code}: {r.text[:500]}")
        try:
            return r.json()
        except ValueError as e:
            raise FakturowniaError(f"Niezrozumiała odpowiedź Fakturowni: {r.text[:300]}") from e

    # ---- produkty ----
    def create_product(self, variant) -> str:
        tax = variant.tax or settings.DEFAULT_TAX
        net = Decimal(variant.purchase_price_net or 0)
        product = {
            "name": variant.display_name,
            "code": variant.sku,
            "ean_code": variant.ean,
            "tax": tax,
            "purchase_tax": tax,
            "purchase_price_net": str(net),
            "purchase_price_gross": str(net_to_gross(net, tax)),
            "limited": "1",
            "quantity_unit": "szt",
            "size": variant.size or "",
        }
        data = self._post("/products.json", {"product": product})
        if "id" not in data:
            raise FakturowniaError(f"Fakturownia nie zwróciła ID produktu: {str(data)[:300]}")
        return str(data["id"])

    # ---- dokumenty magazynowe ----
    def create_document(self, kind: str, warehouse_id: str, lines: list[dict],
                        client_name: str = "", issue_date: str | None = None) -> dict:
        """kind: pz / mm / rw.  lines: gotowe warehouse_actions."""
        doc = {
            "kind": kind,
            "number": None,
            "issue_date": issue_date or local_today(),
            "warehouse_id": warehouse_id,
            "warehouse_actions": lines,
        }
        if client_name:
            doc["client_name"] = client_name
        if settings.FAKTUROWNIA_DEPARTMENT_ID:
            doc["department_id"] = settings.FAKTUROWNIA_DEPARTMENT_ID
        data = self._post("/warehouse_documents.json", {"warehouse_document": doc})
        if "id" not in data:
            raise FakturowniaError(f"Fakturownia nie zwróciła ID dokumentu: {str(data)[:300]}")
        return data


def batch_line(product_id: str, qty: int, price_net, tax: str) -> dict:
    """Jedna linia dokumentu = jedna partia z jej ceną zakupu netto."""
    return {
        "product_id": product_id,
        "quantity": qty,
        "purchase_price_net": str(Decimal(price_net).quantize(Decimal("0.01"))),
        "purchase_tax": tax,
    }
