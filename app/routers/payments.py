from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import Page, opt_date, paged
from ..models import CreditNote, Customer, Invoice, Payment, User
from ..security import require
from ..services import (BizError, audit, customer_totals, find_possible_duplicate, invoice_settled, next_number,
                        payment_dict, validate_payment)
from ..types import d, money

router = APIRouter(prefix="/api", tags=["payments"])
METHODS = Literal["CASH", "UPI", "CARD", "BANK", "CHEQUE", "ONLINE"]


class PaymentIn(BaseModel):
    customer_id: int
    invoice_id: Optional[int] = None
    kind: Literal["PAYMENT", "REFUND"] = "PAYMENT"
    amount: Decimal = Field(gt=0)
    method: METHODS = "CASH"
    reference: str = Field(default="", max_length=100)
    paid_on: Optional[date] = None
    notes: str = ""
    idempotency_key: Optional[str] = Field(default=None, max_length=64)
    confirm_duplicate: bool = False


def _inv_no(db, invoice_id):
    if not invoice_id:
        return ""
    inv = db.get(Invoice, invoice_id)
    return inv.number if inv else ""


def _with_balance(db, p: Payment) -> dict:
    out = payment_dict(p, _inv_no(db, p.invoice_id))
    out["customer_outstanding"] = money(customer_totals(db, p.customer_id)["outstanding"])
    return out


@router.get("/payments")
def list_payments(customer_id: Optional[int] = None, invoice_id: Optional[int] = None, method: str = "",
                  date_from: Optional[str] = None, date_to: Optional[str] = None, include_void: bool = False,
                  page: Page = Depends(), db: Session = Depends(get_db), _: User = Depends(require("payments.record"))):
    stmt = select(Payment)
    if customer_id:
        stmt = stmt.where(Payment.customer_id == customer_id)
    if invoice_id:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    if method:
        stmt = stmt.where(Payment.method == method.upper())
    if date_from:
        stmt = stmt.where(Payment.paid_on >= opt_date(date_from))
    if date_to:
        stmt = stmt.where(Payment.paid_on <= opt_date(date_to))
    if not include_void:
        stmt = stmt.where(Payment.is_void.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(Payment.paid_on.desc(), Payment.id.desc()).offset(page.offset)
                      .limit(page.size)).unique().scalars().all()
    nums = dict(db.execute(select(Invoice.id, Invoice.number).where(
        Invoice.id.in_([p.invoice_id for p in rows if p.invoice_id] or [0]))).all())
    return paged([payment_dict(p, nums.get(p.invoice_id, "")) for p in rows], total, page)


@router.post("/payments")
def record_payment(body: PaymentIn, db: Session = Depends(get_db), user: User = Depends(require("payments.record"))):
    if body.idempotency_key:
        prev = db.execute(select(Payment).where(Payment.idempotency_key == body.idempotency_key)).unique().scalar_one_or_none()
        if prev:
            return {**_with_balance(db, prev), "duplicate_request": True}
    c = db.get(Customer, body.customer_id)
    if not c:
        raise HTTPException(404, "Customer not found.")
    if body.kind == "REFUND" and not user.can("payments.edit"):
        raise HTTPException(403, "You are not allowed to record refunds.")
    amount, paid_on, ref = d(body.amount), body.paid_on or date.today(), body.reference.strip()
    validate_payment(db, c.id, body.invoice_id, body.kind, amount)
    if not body.confirm_duplicate:
        dup = find_possible_duplicate(db, c.id, amount, body.method, ref, paid_on)
        if dup:
            raise BizError(f"This looks like a duplicate of {dup.number} (Rs. {money(dup.amount)} by {dup.method} "
                           f"on {dup.paid_on}). Confirm only if it is really a second payment.", 409,
                           extra={"duplicate_of": dup.number, "needs_confirmation": True})
    try:
        p = Payment(number=next_number(db, "PAY" if body.kind == "PAYMENT" else "RFD"), customer_id=c.id,
                    invoice_id=body.invoice_id, kind=body.kind, amount=amount, method=body.method, reference=ref,
                    paid_on=paid_on, notes=body.notes, idempotency_key=body.idempotency_key, created_by=user.id)
        db.add(p)
        db.flush()
        audit(db, user, "payment_recorded" if body.kind == "PAYMENT" else "refund_recorded", "payment", p.id,
              number=p.number, amount=amount, customer=c.code, invoice_id=body.invoice_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    return _with_balance(db, p)


class PaymentEdit(BaseModel):
    invoice_id: Optional[int] = None
    amount: Decimal = Field(gt=0)
    method: METHODS
    reference: str = ""
    paid_on: date
    notes: str = ""
    reason: str = Field(min_length=3)


@router.put("/payments/{payment_id}")
def edit_payment(payment_id: int, body: PaymentEdit, db: Session = Depends(get_db), user: User = Depends(require("payments.edit"))):
    p = db.get(Payment, payment_id)
    if not p or p.is_void:
        raise HTTPException(400, "Payment not found or already void.")
    amount = d(body.amount)
    validate_payment(db, p.customer_id, body.invoice_id, p.kind, amount, exclude_payment_id=p.id)
    before = {"amount": money(p.amount), "invoice_id": p.invoice_id, "method": p.method, "paid_on": str(p.paid_on)}
    p.invoice_id, p.amount, p.method = body.invoice_id, amount, body.method
    p.reference, p.paid_on, p.notes = body.reference.strip(), body.paid_on, body.notes
    audit(db, user, "payment_edited", "payment", p.id, number=p.number, before=before,
          after={"amount": money(amount), "invoice_id": body.invoice_id, "method": body.method,
                 "paid_on": str(body.paid_on)}, reason=body.reason)
    db.commit()
    return _with_balance(db, p)


class VoidIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


@router.post("/payments/{payment_id}/void")
def void_payment(payment_id: int, body: VoidIn, db: Session = Depends(get_db), user: User = Depends(require("payments.edit"))):
    p = db.get(Payment, payment_id)
    if not p or p.is_void:
        raise HTTPException(400, "Payment not found or already void.")
    p.is_void, p.void_reason = True, body.reason
    audit(db, user, "payment_voided", "payment", p.id, number=p.number, amount=p.amount, reason=body.reason)
    db.commit()
    return _with_balance(db, p)


# ---------------- credit notes
class CreditIn(BaseModel):
    customer_id: int
    invoice_id: Optional[int] = None
    amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=3, max_length=255)
    note_date: Optional[date] = None


@router.get("/credit-notes")
def list_credit_notes(customer_id: Optional[int] = None, page: Page = Depends(), db: Session = Depends(get_db),
                      _: User = Depends(require("payments.record"))):
    stmt = select(CreditNote)
    if customer_id:
        stmt = stmt.where(CreditNote.customer_id == customer_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(CreditNote.id.desc()).offset(page.offset).limit(page.size)).scalars().all()
    return paged([{"id": n.id, "number": n.number, "customer_id": n.customer_id, "invoice_id": n.invoice_id,
                   "amount": money(n.amount), "reason": n.reason, "note_date": n.note_date.isoformat(),
                   "is_void": n.is_void} for n in rows], total, page)


@router.post("/credit-notes")
def create_credit_note(body: CreditIn, db: Session = Depends(get_db), user: User = Depends(require("payments.edit"))):
    if not db.get(Customer, body.customer_id):
        raise HTTPException(404, "Customer not found.")
    amount = d(body.amount)
    if body.invoice_id:
        inv = db.get(Invoice, body.invoice_id)
        if not inv or inv.customer_id != body.customer_id or inv.status != "ISSUED":
            raise HTTPException(400, "Pick an active bill of this customer.")
        due = inv.total - invoice_settled(db, inv.id)["settled"]
        if amount > due:
            raise HTTPException(400, f"Bill {inv.number} has only Rs. {money(due)} due. "
                                     "Give the rest as a credit note without a bill.")
    n = CreditNote(number=next_number(db, "CN"), customer_id=body.customer_id, invoice_id=body.invoice_id,
                   amount=amount, reason=body.reason, note_date=body.note_date or date.today(), created_by=user.id)
    db.add(n)
    db.flush()
    audit(db, user, "credit_note_created", "credit_note", n.id, number=n.number, amount=amount)
    db.commit()
    return {"id": n.id, "number": n.number, "amount": money(n.amount),
            "customer_outstanding": money(customer_totals(db, body.customer_id)["outstanding"])}


@router.post("/credit-notes/{note_id}/void")
def void_credit_note(note_id: int, body: VoidIn, db: Session = Depends(get_db), user: User = Depends(require("payments.edit"))):
    n = db.get(CreditNote, note_id)
    if not n or n.is_void:
        raise HTTPException(400, "Credit note not found or already void.")
    n.is_void = True
    audit(db, user, "credit_note_voided", "credit_note", n.id, number=n.number, reason=body.reason)
    db.commit()
    return {"message": f"{n.number} voided."}
