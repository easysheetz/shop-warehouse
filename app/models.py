"""Model danych.

ProductModel   – model produktu (np. "Bluza Nike Club"); warianty grupują się po nazwie
Variant        – wariant z kodem EAN (rozmiar, kolor) – to on jest skanowany
Purchase       – zakup w sklepie, dostawa z innego źródła albo nadwyżka z przyjęcia.
                 status "koszyk" = trwa skanowanie; każdy skan zapisuje się od razu w bazie.
PurchaseItem   – PARTIA: ilość kupiona po jednej cenie netto (osobna linia na PZ)
Receipt        – przyjęcie na magazyn
ReceiptLine    – zeskanowane pozycje przyjęcia (dobre albo reklamacja z opisem)
ReceiptAlloc   – które partie zostały przyjęte w danym przyjęciu (z tego powstaje MM)
Complaint      – reklamacja: towar na magazynie "Reklamacje" z opisem usterki
Writeoff       – odpis braku z magazynu "W drodze" (dokument RW)
SyncLog        – dziennik wysyłek do Fakturowni

Każda zmiana w tym pliku wymaga migracji:  alembic revision --autogenerate -m "opis"
"""
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    pin_hash: Mapped[str] = mapped_column(String(200))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProductModel(Base):
    __tablename__ = "product_models"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    name_key: Mapped[str] = mapped_column(String(255), unique=True)  # nazwa małymi literami – do grupowania
    brand: Mapped[str] = mapped_column(String(120), default="")
    category: Mapped[str] = mapped_column(String(120), default="")
    tax: Mapped[str] = mapped_column(String(8), default="23")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    variants: Mapped[list["Variant"]] = relationship(back_populates="model")


class Variant(Base):
    __tablename__ = "variants"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("product_models.id"), index=True)
    ean: Mapped[str] = mapped_column(String(32), unique=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True)
    size: Mapped[str] = mapped_column(String(40), default="")
    color: Mapped[str] = mapped_column(String(80), default="")
    purchase_price_net: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)  # ostatnia cena – podpowiedź
    fakturownia_product_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    model: Mapped[ProductModel] = relationship(back_populates="variants")
    created_by: Mapped["User | None"] = relationship()

    @property
    def display_name(self) -> str:
        extra = ", ".join(x for x in (self.size, self.color) if x)
        return f"{self.model.name} – {extra}" if extra else self.model.name

    @property
    def tax(self) -> str:
        return self.model.tax


class Purchase(Base):
    __tablename__ = "purchases"
    __table_args__ = (
        # najwyżej jeden otwarty koszyk danego rodzaju na osobę
        Index("uq_open_cart", "user_id", "source_type", unique=True,
              postgresql_where=text("status = 'koszyk'"), sqlite_where=text("status = 'koszyk'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20), default="sklep")  # sklep / dostawa / nadwyzka
    source_name: Mapped[str] = mapped_column(String(160), default="")      # sklep / hurtownia
    invoice_number: Mapped[str] = mapped_column(String(80), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # magazyn docelowy dokumentu PZ: transit (normalnie) / main / returns (nadwyżka przy przyjęciu)
    target: Mapped[str] = mapped_column(String(10), default="transit")
    # koszyk / w_drodze / czesciowo / przyjety / zamkniety (reszta odpisana)
    status: Mapped[str] = mapped_column(String(20), default="koszyk", index=True)
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("receipts.id"), nullable=True)  # dla nadwyżek
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    bought_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # zakończenie zakupu
    fakt_doc_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fakt_doc_number: Mapped[str] = mapped_column(String(80), default="")
    sync_status: Mapped[str] = mapped_column(String(12), default="oczekuje", index=True)  # oczekuje/ok/blad/wylaczone
    sync_error: Mapped[str] = mapped_column(Text, default="")
    user: Mapped[User] = relationship()
    items: Mapped[list["PurchaseItem"]] = relationship(back_populates="purchase", order_by="PurchaseItem.id",
                                                       cascade="all, delete-orphan")


class PurchaseItem(Base):
    """Partia towaru."""
    __tablename__ = "purchase_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), index=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_net: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax: Mapped[str] = mapped_column(String(8), default="23")
    is_new_product: Mapped[bool] = mapped_column(Boolean, default=False)  # produkt dodany przy tym zakupie
    received_qty: Mapped[int] = mapped_column(Integer, default=0)      # przyjęte na magazyn główny
    damaged_qty: Mapped[int] = mapped_column(Integer, default=0)       # przyjęte jako reklamacja
    written_off_qty: Mapped[int] = mapped_column(Integer, default=0)   # odpisane braki
    purchase: Mapped[Purchase] = relationship(back_populates="items")
    variant: Mapped[Variant] = relationship()

    @property
    def remaining(self) -> int:
        return self.qty - self.received_qty - self.damaged_qty - self.written_off_qty


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (
        # w danej chwili jest jedno wspólne otwarte przyjęcie
        Index("uq_open_receipt", "status", unique=True,
              postgresql_where=text("status = 'otwarte'"), sqlite_where=text("status = 'otwarte'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="otwarte", index=True)  # otwarte / zatwierdzone
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    mm_main_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mm_main_number: Mapped[str] = mapped_column(String(80), default="")
    mm_returns_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mm_returns_number: Mapped[str] = mapped_column(String(80), default="")
    sync_status: Mapped[str] = mapped_column(String(12), default="oczekuje", index=True)
    sync_error: Mapped[str] = mapped_column(Text, default="")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    confirmed_by: Mapped["User | None"] = relationship(foreign_keys=[confirmed_by_id])
    lines: Mapped[list["ReceiptLine"]] = relationship(back_populates="receipt", order_by="ReceiptLine.id",
                                                      cascade="all, delete-orphan")
    allocs: Mapped[list["ReceiptAlloc"]] = relationship(back_populates="receipt", cascade="all, delete-orphan")


class ReceiptLine(Base):
    __tablename__ = "receipt_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), index=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    damaged: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")  # opis usterki dla reklamacji
    scanned_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    receipt: Mapped[Receipt] = relationship(back_populates="lines")
    variant: Mapped[Variant] = relationship()


class ReceiptAlloc(Base):
    __tablename__ = "receipt_allocs"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), index=True)
    purchase_item_id: Mapped[int] = mapped_column(ForeignKey("purchase_items.id"))
    qty: Mapped[int] = mapped_column(Integer)
    damaged: Mapped[bool] = mapped_column(Boolean, default=False)
    receipt: Mapped[Receipt] = relationship(back_populates="allocs")
    item: Mapped[PurchaseItem] = relationship()


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"))
    purchase_item_id: Mapped[int] = mapped_column(ForeignKey("purchase_items.id"))
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"))
    qty: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="otwarta", index=True)  # otwarta / zamknieta
    resolution: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    variant: Mapped[Variant] = relationship()
    item: Mapped[PurchaseItem] = relationship()


class Writeoff(Base):
    __tablename__ = "writeoffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_item_id: Mapped[int] = mapped_column(ForeignKey("purchase_items.id"))
    qty: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    fakt_doc_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fakt_doc_number: Mapped[str] = mapped_column(String(80), default="")
    sync_status: Mapped[str] = mapped_column(String(12), default="oczekuje", index=True)
    sync_error: Mapped[str] = mapped_column(Text, default="")
    item: Mapped[PurchaseItem] = relationship()
    user: Mapped[User] = relationship()


class SyncLog(Base):
    __tablename__ = "sync_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(40))
    ref: Mapped[str] = mapped_column(String(80), default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
