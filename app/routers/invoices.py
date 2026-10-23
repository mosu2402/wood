from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import Page, opt_date, paged, pdf_response
from ..models import CreditNote, Customer, FactoryOrder, Invoice, Payment, User, now
from ..pdf import invoice_pdf
from ..security import require, require_any
from ..services import (BizError, apply_invoice_lines, audit, customer_dict, factory_dict, invoice_dict,
                        invoice_settled, next_number, payment_dict, reverse_invoice_effects, settled_map,
                        validate_payment)
from ..types import d, money

router = APIRouter(prefix="/api/invoices", tags=["billing"])


class LineIn(BaseModel):
    product_id: int
    qty: Decimal = Field(gt=0)
    rate: Optional[Decimal] = None
    discount_pct: Decimal = Field(default=Decimal(0), ge=0, le=100)
    fulfilment: Literal["STOCK", "FACTORY"] = "STOCK"
    dimensions: str = ""
    finish: str = ""
    instructions: str = ""


class InlinePayment(BaseModel):
    amount: Decimal = Field(gt=0)
    method: Literal["CASH", "UPI", "CARD", "BANK", "CHEQUE", "ONLINE"] = "CASH"
    reference: str = ""


class InvoiceIn(BaseModel):
    customer_id: int
    invoice_date: Optional[date] = None
    source: Literal["MANUAL", "ONLINE", "DELIVERY", "BULK"] = "MANUAL"
    tax_mode: Literal["BILL", "CASH"] = "BILL"
    notes: str = ""
    lines: list[LineIn] = Field(min_length=1)
    payment: Optional[InlinePayment] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=64)


def settled_subqueries():
    pay = (select(Payment.invoice_id.label("iid"),
                  func.sum(case((Payment.kind == "PAYMENT", Payment.amount), else_=-Payment.amount)).label("s"))
           .where(Payment.is_void.is_(False), Payment.invoice_id.is_not(None)).group_by(Payment.invoice_id).subquery())
    cn = (select(CreditNote.invoice_id.label("iid"), func.sum(CreditNote.amount).label("s"))
          .where(CreditNote.is_void.is_(False), CreditNote.invoice_id.is_not(None)).group_by(CreditNote.invoice_id)
          .subquery())
    return pay, cn


@router.get("")
def list_invoices(q: str = "", customer_id: Optional[int] = None, date_from: Optional[str] = None,
                  date_to: Optional[str] = None, status: str = "", payment_status: str = "", source: str = "", tax_mode: str = "",
                  page: Page = Depends(), db: Session = Depends(get_db),
                  user: User = Depends(require_any("billing.create", "customers.view", "payments.record"))):
    stmt = select(Invoice)
    if q:
        stmt = stmt.join(Customer, Customer.id == Invoice.customer_id).where(
            (Invoice.number == q.strip().upper()) | Customer.name.ilike(f"%{q.strip()}%") | (Customer.phone == q.strip()))
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= opt_date(date_from))
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= opt_date(date_to))
    if status:
        stmt = stmt.where(Invoice.status == status.upper())
    if tax_mode:
        stmt = stmt.where(Invoice.tax_mode == tax_mode.upper())
    if source:
        stmt = stmt.where(Invoice.source == source.upper())
    if payment_status:
        pay, cn = settled_subqueries()
        settled = func.coalesce(pay.c.s, 0) + func.coalesce(cn.c.s, 0)
        stmt = stmt.outerjoin(pay, pay.c.iid == Invoice.id).outerjoin(cn, cn.c.iid == Invoice.id)
        ps = payment_status.upper()
        if ps == "PAID":
            stmt = stmt.where(Invoice.status == "ISSUED", settled >= Invoice.total)
        elif ps == "PARTIAL":
            stmt = stmt.where(Invoice.status == "ISSUED", settled > 0, settled < Invoice.total)
        elif ps == "UNPAID":
            stmt = stmt.where(Invoice.status == "ISSUED", settled <= 0, Invoice.total > 0)
        elif ps == "DUE":
            stmt = stmt.where(Invoice.status == "ISSUED", settled < Invoice.total)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).offset(page.offset)
                      .limit(page.size)).unique().scalars().all()
    smap = settled_map(db, [i.id for i in rows])
    return paged([invoice_dict(db, i, user, with_lines=False, settled=smap[i.id]) for i in rows], total, page)


def _full(db: Session, inv: Invoice, user: User) -> dict:
    out = invoice_dict(db, inv, user)
    out["customer"] = customer_dict(inv.customer)
    payments = db.execute(select(Payment).where(Payment.invoice_id == inv.id).order_by(Payment.id)).unique().scalars().all()
    out["payments"] = [payment_dict(p, inv.number) for p in payments]
    out["credit_notes"] = [{"number": n.number, "amount": money(n.amount), "reason": n.reason,
                            "note_date": n.note_date.isoformat(), "is_void": n.is_void}
                           for n in db.execute(select(CreditNote).where(CreditNote.invoice_id == inv.id)).scalars()]
    out["factory_orders"] = [factory_dict(fo, user) for fo in db.execute(
        select(FactoryOrder).where(FactoryOrder.invoice_id == inv.id)).unique().scalars()]
    return out


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_any("billing.create", "customers.view", "payments.record"))):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Bill not found.")
    return _full(db, inv, user)


@router.post("")
def create_invoice(body: InvoiceIn, db: Session = Depends(get_db), user: User = Depends(require("billing.create"))):
    if body.idempotency_key:
        existing = db.execute(select(Invoice).where(Invoice.idempotency_key == body.idempotency_key)).unique().scalar_one_or_none()
        if existing:
            return {**_full(db, existing, user), "duplicate_request": True}
    customer = db.get(Customer, body.customer_id)
    if not customer or not customer.is_active:
        raise HTTPException(400, "Select an active customer first.")
    if body.payment and not user.can("payments.record"):
        raise HTTPException(403, "You are not allowed to record payments.")
    try:
        inv = Invoice(number=next_number(db, "INV"), customer_id=customer.id, invoice_date=body.invoice_date or date.today(),
                      source=body.source, tax_mode=body.tax_mode, notes=body.notes, created_by=user.id,
                      idempotency_key=body.idempotency_key)
        db.add(inv)
        db.flush()
        apply_invoice_lines(db, inv, [l.model_dump() for l in body.lines], user)
        if body.payment:
            amt = d(body.payment.amount)
            validate_payment(db, customer.id, inv.id, "PAYMENT", amt)
            db.add(Payment(number=next_number(db, "PAY"), customer_id=customer.id, invoice_id=inv.id, kind="PAYMENT",
                           amount=amt, method=body.payment.method, reference=body.payment.reference.strip(),
                           paid_on=inv.invoice_date, created_by=user.id))
        audit(db, user, "invoice_created", "invoice", inv.id, number=inv.number, total=inv.total, customer=customer.code)
        db.commit()
    except (BizError, IntegrityError):
        db.rollback()
        raise
    db.refresh(inv)
    return _full(db, inv, user)


@router.put("/{invoice_id}")
def edit_invoice(invoice_id: int, body: InvoiceIn, db: Session = Depends(get_db), user: User = Depends(require("billing.edit"))):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Bill not found.")
    if inv.status != "ISSUED":
        raise HTTPException(400, "A cancelled bill cannot be edited.")
    if body.customer_id != inv.customer_id:
        raise HTTPException(400, "The customer of a bill cannot be changed. Cancel it and create a new bill.")
    try:
        old_total = inv.total
        reverse_invoice_effects(db, inv, user, "edited")
        inv.lines.clear()
        db.flush()
        inv.invoice_date = body.invoice_date or inv.invoice_date
        inv.source, inv.notes, inv.tax_mode = body.source, body.notes, body.tax_mode
        apply_invoice_lines(db, inv, [l.model_dump() for l in body.lines], user)
        settled = invoice_settled(db, inv.id)["settled"]
        if inv.total < settled:
            raise BizError(f"New total Rs. {money(inv.total)} is less than the Rs. {money(settled)} already paid. "
                           "Refund or move the extra payment first.")
        audit(db, user, "invoice_edited", "invoice", inv.id, number=inv.number, old_total=old_total, new_total=inv.total)
        db.commit()
    except BizError:
        db.rollback()
        raise
    db.refresh(inv)
    return _full(db, inv, user)


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


@router.post("/{invoice_id}/cancel")
def cancel_invoice(invoice_id: int, body: CancelIn, db: Session = Depends(get_db), user: User = Depends(require("billing.edit"))):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.status != "ISSUED":
        raise HTTPException(400, "Only an active bill can be cancelled.")
    s = invoice_settled(db, inv.id)
    if s["paid"] - s["refunded"] > 0 or s["credited"] > 0:
        raise HTTPException(400, "This bill has payments or credit notes. Void or refund them first, "
                                 "or move the payment to an advance.")
    try:
        reverse_invoice_effects(db, inv, user, "cancelled")
        inv.status, inv.cancel_reason = "CANCELLED", body.reason
        audit(db, user, "invoice_cancelled", "invoice", inv.id, number=inv.number, reason=body.reason)
        db.commit()
    except BizError:
        db.rollback()
        raise
    return _full(db, inv, user)


class DeliveryIn(BaseModel):
    delivered: bool


@router.post("/{invoice_id}/delivery")
def set_delivery(invoice_id: int, body: DeliveryIn, db: Session = Depends(get_db), user: User = Depends(require("billing.create"))):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.status != "ISSUED":
        raise HTTPException(400, "Bill not found or cancelled.")
    inv.delivery_status = "DELIVERED" if body.delivered else "PENDING"
    inv.delivered_at = now() if body.delivered else None
    audit(db, user, "invoice_delivery", "invoice", inv.id, delivered=body.delivered)
    db.commit()
    return {"delivery_status": inv.delivery_status}


@router.get("/{invoice_id}/pdf")
def pdf(invoice_id: int, db: Session = Depends(get_db),
        user: User = Depends(require_any("billing.create", "customers.view", "payments.record"))):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Bill not found.")
    data = _full(db, inv, user)
    return pdf_response(invoice_pdf(data, data["customer"], data["payments"]), f"{inv.number}.pdf")
