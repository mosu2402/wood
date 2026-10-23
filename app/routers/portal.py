"""Customer self-service. Every query is pinned to the logged-in customer's own id,
taken from the server-side user record, never from the request."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import file_response, pdf_response
from ..models import Invoice, Payment, User
from ..pdf import invoice_pdf
from ..security import require_customer
from ..services import customer_account, customer_dict, invoice_dict, payment_dict
from .customers import XLSX, build_customer_xlsx, build_statement

router = APIRouter(prefix="/api/me", tags=["customer portal"])


@router.get("/account")
def my_account(db: Session = Depends(get_db), user: User = Depends(require_customer)):
    return customer_account(db, user.customer_id, user)


@router.get("/invoices/{invoice_id}/pdf")
def my_invoice_pdf(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_customer)):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.customer_id != user.customer_id:
        raise HTTPException(404, "Bill not found.")  # same message whether it exists or not
    data = invoice_dict(db, inv, user)
    pays = [payment_dict(p, inv.number) for p in db.execute(
        select(Payment).where(Payment.invoice_id == inv.id, Payment.customer_id == user.customer_id)).unique().scalars()]
    return pdf_response(invoice_pdf(data, customer_dict(inv.customer), pays), f"{inv.number}.pdf")


@router.get("/statement.pdf")
def my_statement(date_from: Optional[str] = None, date_to: Optional[str] = None, db: Session = Depends(get_db),
                 user: User = Depends(require_customer)):
    content, code = build_statement(db, user.customer_id, user, date_from, date_to)
    return pdf_response(content, f"statement_{code}.pdf")


@router.get("/export.xlsx")
def my_export(db: Session = Depends(get_db), user: User = Depends(require_customer)):
    content, name = build_customer_xlsx(db, user.customer_id, user)
    return file_response(content, name, XLSX)
