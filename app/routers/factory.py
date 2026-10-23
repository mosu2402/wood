from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import Page, opt_date, paged, pdf_response
from ..models import FACTORY_STATUSES, Customer, FactoryOrder, FactoryOrderEvent, FactoryOrderLine, Product, User
from ..pdf import factory_order_pdf
from ..security import require
from ..services import BizError, audit, factory_dict, next_number, set_factory_status
from ..types import d

router = APIRouter(prefix="/api/factory-orders", tags=["factory orders"])
perm = require("factory.manage")


@router.get("/statuses")
def statuses(_: User = Depends(perm)):
    return FACTORY_STATUSES


@router.get("")
def list_orders(status: str = "", customer_id: Optional[int] = None, supplier_id: Optional[int] = None,
                q: str = "", date_from: Optional[str] = None, date_to: Optional[str] = None,
                page: Page = Depends(), db: Session = Depends(get_db), user: User = Depends(perm)):
    stmt = select(FactoryOrder)
    if status == "OPEN":
        stmt = stmt.where(FactoryOrder.status.not_in(["DELIVERED", "CANCELLED"]))
    elif status:
        stmt = stmt.where(FactoryOrder.status == status.upper())
    if customer_id:
        stmt = stmt.where(FactoryOrder.customer_id == customer_id)
    if supplier_id:
        stmt = stmt.where(FactoryOrder.supplier_id == supplier_id)
    if q:
        s = q.strip().upper()
        sub = select(FactoryOrderLine.order_id).where(
            (FactoryOrderLine.factory_order_no == s) | (FactoryOrderLine.catalogue_no == s))
        stmt = stmt.where((FactoryOrder.number == s) | FactoryOrder.id.in_(sub))
    if date_from:
        stmt = stmt.where(func.date(FactoryOrder.created_at) >= opt_date(date_from))
    if date_to:
        stmt = stmt.where(func.date(FactoryOrder.created_at) <= opt_date(date_to))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(FactoryOrder.id.desc()).offset(page.offset).limit(page.size)).unique().scalars().all()
    counts = dict(db.execute(select(FactoryOrder.status, func.count()).group_by(FactoryOrder.status)).all())
    out = paged([factory_dict(o, user) for o in rows], total, page)
    out["counts"] = {s: counts.get(s, 0) for s in FACTORY_STATUSES}
    return out


class OrderLineIn(BaseModel):
    product_id: int
    qty: Decimal = Field(gt=0)
    dimensions: str = ""
    finish: str = ""
    instructions: str = ""


class OrderIn(BaseModel):
    customer_id: Optional[int] = None
    expected_date: Optional[date] = None
    notes: str = ""
    lines: list[OrderLineIn] = Field(min_length=1)


@router.post("")
def create_order(body: OrderIn, db: Session = Depends(get_db), user: User = Depends(perm)):
    """Standalone factory order (stock replenishment, or a customer order before billing).
    Products from different factories are split into separate orders automatically."""
    if body.customer_id and not db.get(Customer, body.customer_id):
        raise HTTPException(404, "Customer not found.")
    by_supplier: dict[int, list] = {}
    for i, li in enumerate(body.lines, 1):
        p = db.get(Product, li.product_id)
        if not p or not p.is_active:
            raise HTTPException(400, f"Line {i}: product not found or switched off.")
        by_supplier.setdefault(p.supplier_id, []).append((p, li))
    created = []
    for sid, items in by_supplier.items():
        fo = FactoryOrder(number=next_number(db, "FO"), customer_id=body.customer_id, supplier_id=sid, status="PENDING",
                          expected_date=body.expected_date, notes=body.notes, created_by=user.id)
        for p, li in items:
            fo.lines.append(FactoryOrderLine(product_id=p.id, catalogue=p.catalogue, catalogue_no=p.catalogue_no,
                                             factory_order_no=p.factory_order_no, product_name=p.name, unit=p.unit,
                                             qty=d(li.qty, "0.001"), dimensions=li.dimensions,
                                             finish=li.finish or p.finish, instructions=li.instructions))
        fo.events.append(FactoryOrderEvent(from_status="", to_status="PENDING", note="Created", user_id=user.id))
        db.add(fo)
        db.flush()
        audit(db, user, "factory_order_created", "factory_order", fo.id, number=fo.number)
        created.append(fo)
    db.commit()
    return [factory_dict(o, user) for o in created]


@router.get("/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(perm)):
    fo = db.get(FactoryOrder, order_id)
    if not fo:
        raise HTTPException(404, "Factory order not found.")
    return factory_dict(fo, user)


class StatusIn(BaseModel):
    status: str
    note: str = ""


@router.post("/{order_id}/status")
def change_status(order_id: int, body: StatusIn, db: Session = Depends(get_db), user: User = Depends(perm)):
    fo = db.get(FactoryOrder, order_id)
    if not fo:
        raise HTTPException(404, "Factory order not found.")
    try:
        set_factory_status(db, fo, body.status, user, body.note)
        db.commit()
    except BizError:
        db.rollback()
        raise
    return factory_dict(fo, user)


class OrderEdit(BaseModel):
    expected_date: Optional[date] = None
    notes: str = ""


@router.patch("/{order_id}")
def edit_order(order_id: int, body: OrderEdit, db: Session = Depends(get_db), user: User = Depends(perm)):
    fo = db.get(FactoryOrder, order_id)
    if not fo:
        raise HTTPException(404, "Factory order not found.")
    fo.expected_date, fo.notes = body.expected_date, body.notes
    audit(db, user, "factory_order_edited", "factory_order", fo.id)
    db.commit()
    return factory_dict(fo, user)


@router.get("/{order_id}/pdf")
def pdf(order_id: int, db: Session = Depends(get_db), user: User = Depends(perm)):
    fo = db.get(FactoryOrder, order_id)
    if not fo:
        raise HTTPException(404, "Factory order not found.")
    return pdf_response(factory_order_pdf(factory_dict(fo, user)), f"{fo.number}.pdf")
