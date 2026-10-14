"""Kontrola sekretów przy starcie: produkcja nie wystartuje z wartościami domyślnymi."""
import pytest

from app.config import Settings


def make(monkeypatch, **env):
    for k in ("APP_ENV", "SECRET_KEY", "DATABASE_URL", "SYNC_TOKEN", "ADMIN_PIN", "FAKTUROWNIA_ENABLED",
              "FAKTUROWNIA_TOKEN", "FAKTUROWNIA_DOMAIN", "FAKTUROWNIA_BASE_URL", "WAREHOUSE_TRANSIT_ID",
              "WAREHOUSE_MAIN_ID", "WAREHOUSE_RETURNS_ID"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings()


def test_production_refuses_defaults(monkeypatch):
    s = make(monkeypatch, APP_ENV="production", ADMIN_PIN="1234")
    text = "\n".join(s.problems())
    for name in ("SECRET_KEY", "DATABASE_URL", "SYNC_TOKEN", "ADMIN_PIN"):
        assert name in text
    with pytest.raises(RuntimeError):
        s.validate()


def test_production_ok_with_real_secrets(monkeypatch):
    s = make(monkeypatch, APP_ENV="production", SECRET_KEY="x" * 40, SYNC_TOKEN="y" * 40, ADMIN_PIN="583920",
             DATABASE_URL="postgresql+psycopg://app:haslo@/skaner?host=/cloudsql/projekt:europe-central2:baza")
    assert s.problems() == []


def test_fakturownia_requires_token_and_warehouses(monkeypatch):
    s = make(monkeypatch, FAKTUROWNIA_ENABLED="true")
    text = "\n".join(s.problems())
    assert "FAKTUROWNIA_TOKEN" in text and "WAREHOUSE_MAIN_ID" in text and "FAKTUROWNIA_DOMAIN" in text


def test_development_defaults_are_fine(monkeypatch):
    assert make(monkeypatch).problems() == []
