"""Relational schema for the Luxe Laminate Management System.

Design rules:
* Every product has one internal id plus exactly two business numbers:
  catalogue_no (what the customer sees) and factory_order_no (what the factory needs).
* Invoice lines and factory-order lines SNAPSHOT both numbers, the name and the
  rate at the moment of sale, so later mapping changes never alter old documents.
* Customer balances are always computed from invoices / payments / credit notes,
  never stored, so they cannot drift out of sync.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .types import Money, Percent, Qty


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


ZERO = Decimal("0")

ROLES = ("owner", "staff", "customer")

# Permissions the owner can grant to staff
PERMISSIONS = {
    "products.view": "See products and stock",
    "products.edit": "Add and edit products and number mappings",
    "inventory.import": "Import / bulk update inventory from Excel",
    "stock.manage": "Record stock in, returns, damage and adjustments",
    "customers.view": "Search customers and see their accounts",
    "customers.edit": "Add and edit customers",
    "billing.create": "Create bills",
    "billing.edit": "Edit or cancel bills",
    "billing.override_price": "Change the rate on a bill line",
    "payments.record": "Record payments",
    "payments.edit": "Edit or void payments, refunds and credit notes",
    "factory.manage": "Create and update factory orders",
    "purchases.manage": "Record purchases from suppliers",
    "expenses.manage": "Record expenses",
    "reports.view": "See dashboard and reports",
    "costs.view": "See purchase costs, suppliers and profit",
}

FACTORY_STATUSES = ["PENDING", "APPROVED", "SENT_TO_FACTORY", "IN_PRODUCTION",
                    "READY", "DISPATCHED", "DELIVERED", "CANCELLED"]


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), index=True)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    def can(self, perm: str) -> bool:
        if not self.is_active:
            return False
        if self.role == "owner":
            return True
        return self.role == "staff" and perm in (self.permissions or [])


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("catalogue", "catalogue_no", name="uq_product_catalogue_no"),
        UniqueConstraint("supplier_id", "factory_order_no", name="uq_product_factory_no"),
        Index("ix_product_catalogue_no", "catalogue_no"),
        Index("ix_product_factory_no", "factory_order_no"),
        Index("ix_product_name", "name"),
        Index("ix_product_category", "category_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    catalogue: Mapped[str] = mapped_column(String(60), default="MAIN")
    catalogue_no: Mapped[str] = mapped_column(String(60))
    factory_order_no: Mapped[str] = mapped_column(String(60))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(80), default="", server_default="")
    hsn: Mapped[str] = mapped_column(String(20), default="", server_default="")
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    size: Mapped[str] = mapped_column(String(100), default="")
    finish: Mapped[str] = mapped_column(String(100), default="")
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    sale_price: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    purchase_cost: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    tax_rate: Mapped[Decimal] = mapped_column(Percent, default=Decimal("18"))
    stock_qty: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    reserved_qty: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    damaged_qty: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    reorder_level: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    supplier = relationship("Supplier", lazy="joined")
    category = relationship("Category", lazy="joined")

    @property
    def available_qty(self) -> Decimal:
        return (self.stock_qty or ZERO) - (self.reserved_qty or ZERO)


class ProductMappingHistory(Base):
    __tablename__ = "product_mapping_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    old_catalogue: Mapped[str] = mapped_column(String(60), default="")
    old_catalogue_no: Mapped[str] = mapped_column(String(60), default="")
    old_factory_order_no: Mapped[str] = mapped_column(String(60), default="")
    old_supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_catalogue: Mapped[str] = mapped_column(String(60), default="")
    new_catalogue_no: Mapped[str] = mapped_column(String(60), default="")
    new_factory_order_no: Mapped[str] = mapped_column(String(60), default="")
    new_supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    changed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (Index("ix_stock_mv_product_date", "product_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    kind: Mapped[str] = mapped_column(String(20))  # IN OUT RETURN DAMAGE WRITE_OFF ADJUST RESERVE UNRESERVE
    qty: Mapped[Decimal] = mapped_column(Qty)
    stock_after: Mapped[Decimal] = mapped_column(Qty)
    reserved_after: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    ref_type: Mapped[str] = mapped_column(String(30), default="")
    ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    phone: Mapped[str] = mapped_column(String(30), index=True, default="")
    area: Mapped[str] = mapped_column(String(80), index=True, default="", server_default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    gstin: Mapped[str] = mapped_column(String(20), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (Index("ix_invoice_customer_date", "customer_id", "invoice_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    invoice_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(20), default="MANUAL")  # MANUAL ONLINE DELIVERY BULK
    tax_mode: Mapped[str] = mapped_column(String(10), default="BILL", server_default="BILL", index=True)  # BILL=GST, CASH=no GST
    status: Mapped[str] = mapped_column(String(20), default="ISSUED", index=True)  # ISSUED CANCELLED
    subtotal: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    discount_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    taxable_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    tax_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    cost_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    notes: Mapped[str] = mapped_column(Text, default="")
    delivery_status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING DELIVERED
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    cancel_reason: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    customer = relationship("Customer", lazy="joined")
    lines = relationship("InvoiceLine", cascade="all, delete-orphan", order_by="InvoiceLine.id",
                         back_populates="invoice")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    catalogue: Mapped[str] = mapped_column(String(60))
    catalogue_no: Mapped[str] = mapped_column(String(60))
    factory_order_no: Mapped[str] = mapped_column(String(60))
    product_name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(80), default="", server_default="")
    hsn: Mapped[str] = mapped_column(String(20), default="", server_default="")
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    qty: Mapped[Decimal] = mapped_column(Qty)
    rate: Mapped[Decimal] = mapped_column(Money)
    discount_pct: Mapped[Decimal] = mapped_column(Percent, default=ZERO)
    tax_rate: Mapped[Decimal] = mapped_column(Percent, default=ZERO)
    gross: Mapped[Decimal] = mapped_column(Money)
    discount_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    taxable: Mapped[Decimal] = mapped_column(Money)
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    line_total: Mapped[Decimal] = mapped_column(Money)
    cost_rate: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    cost_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    fulfilment: Mapped[str] = mapped_column(String(10), default="STOCK")  # STOCK FACTORY
    dimensions: Mapped[str] = mapped_column(String(120), default="")
    finish: Mapped[str] = mapped_column(String(100), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")

    invoice = relationship("Invoice", back_populates="lines")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (Index("ix_payment_customer_date", "customer_id", "paid_on"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    invoice_id: Mapped[Optional[int]] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(10), default="PAYMENT")  # PAYMENT REFUND
    amount: Mapped[Decimal] = mapped_column(Money)
    method: Mapped[str] = mapped_column(String(20))  # CASH UPI CARD BANK CHEQUE ONLINE
    reference: Mapped[str] = mapped_column(String(100), default="")
    paid_on: Mapped[date] = mapped_column(Date, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    is_void: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    void_reason: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    customer = relationship("Customer", lazy="joined")


class CreditNote(Base):
    __tablename__ = "credit_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    reason: Mapped[str] = mapped_column(String(255), default="")
    note_date: Mapped[date] = mapped_column(Date, index=True)
    is_void: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class FactoryOrder(Base):
    __tablename__ = "factory_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    stock_received: Mapped[bool] = mapped_column(Boolean, default=False)
    stock_issued: Mapped[bool] = mapped_column(Boolean, default=False)
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    customer = relationship("Customer", lazy="joined")
    supplier = relationship("Supplier", lazy="joined")
    lines = relationship("FactoryOrderLine", cascade="all, delete-orphan", order_by="FactoryOrderLine.id")
    events = relationship("FactoryOrderEvent", cascade="all, delete-orphan", order_by="FactoryOrderEvent.id")


class FactoryOrderLine(Base):
    __tablename__ = "factory_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("factory_orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    invoice_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("invoice_lines.id"), nullable=True)
    catalogue: Mapped[str] = mapped_column(String(60))
    catalogue_no: Mapped[str] = mapped_column(String(60))
    factory_order_no: Mapped[str] = mapped_column(String(60))
    product_name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    qty: Mapped[Decimal] = mapped_column(Qty)
    dimensions: Mapped[str] = mapped_column(String(120), default="")
    finish: Mapped[str] = mapped_column(String(100), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")


class FactoryOrderEvent(Base):
    __tablename__ = "factory_order_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("factory_orders.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str] = mapped_column(String(20), default="")
    to_status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    qty: Mapped[Decimal] = mapped_column(Qty)
    unit_cost: Mapped[Decimal] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money)
    purchase_date: Mapped[date] = mapped_column(Date, index=True)
    supplier_bill_no: Mapped[str] = mapped_column(String(60), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_void: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    supplier = relationship("Supplier", lazy="joined")
    product = relationship("Product", lazy="joined")


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(80), default="General")
    amount: Mapped[Decimal] = mapped_column(Money)
    description: Mapped[str] = mapped_column(Text, default="")
    is_void: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(60), default="")
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class Counter(Base):
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(10))  # create | upsert
    status: Mapped[str] = mapped_column(String(20), default="PREVIEW")  # PREVIEW COMMITTED DISCARDED
    rows: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    committed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AppSetting(Base):
    """Small owner-editable settings, e.g. the monthly sales target."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
