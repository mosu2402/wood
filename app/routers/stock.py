from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import Page, opt_date, paged
from ..models import Expense, Product, Purchase, StockMovement, Supplier, User
from ..security import require, require_any
from ..services import BizError, audit, lock_product, move_stock, product_dict
from ..types import d, money, qty

router = APIRouter(prefix="/api", tags=["stock, purchases, expenses"])


class MoveIn(BaseModel):
    product_id: int
    kind: Literal["IN", "RETURN", "DAMAGE", "WRITE_OFF", "ADJUST"]
    qty: Decimal
    note: str = Field(min_length=2, max_length=255)


@router.post("/stock/movements")
def record_movement(body: MoveIn, db: Session = Depends(get_db), user: User = Depends(require("stock.manage"))):
    try:
        p = lock_product(db, body.product_id)
        mv = move_stock(db, p, body.kind, body.qty, user, "manual", None, body.note)
        db.flush()
        audit(db, user, "stock_" + body.kind.lower(), "product", p.id, qty=body.qty, note=body.note)
        db.commit()
    except BizError:
        db.rollback()
        raise
    return {"movement_id": mv.id, "product": product_dict(p, user)}


@router.get("/stock/movements")
def list_movements(product_id: Optional[int] = None, kind: str = "", date_from: Optional[str] = None,
                   date_to: Optional[str] = None, page: Page = Depends(), db: Session = Depends(get_db),
                   _: User = Depends(require_any("stock.manage", "products.view"))):
    stmt = select(StockMovement, Product.name, Product.catalogue_no).join(Product, Product.id == StockMovement.product_id)
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if kind:
        stmt = stmt.where(StockMovement.kind == kind.upper())
    if date_from:
        stmt = stmt.where(func.date(StockMovement.created_at) >= opt_date(date_from))
    if date_to:
        stmt = stmt.where(func.date(StockMovement.created_at) <= opt_date(date_to))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(StockMovement.id.desc()).offset(page.offset).limit(page.size)).all()
    return paged([{"id": m.id, "product_id": m.product_id, "product_name": n, "catalogue_no": c, "kind": m.kind,
                   "qty": qty(m.qty), "stock_after": qty(m.stock_after), "reserved_after": qty(m.reserved_after),
                   "ref_type": m.ref_type, "ref_id": m.ref_id, "note": m.note, "at": m.created_at.isoformat()}
                  for m, n, c in rows], total, page)


@router.get("/stock/summary")
def stock_summary(db: Session = Depends(get_db), _: User = Depends(require_any("stock.manage", "products.view"))):
    row = db.execute(select(func.count(Product.id), func.coalesce(func.sum(Product.stock_qty), 0),
                            func.coalesce(func.sum(Product.reserved_qty), 0),
                            func.coalesce(func.sum(Product.damaged_qty), 0)).where(Product.is_active.is_(True))).one()
    low = db.scalar(select(func.count()).where(Product.is_active.is_(True), Product.reorder_level > 0,
                                               Product.stock_qty - Product.reserved_qty <= Product.reorder_level))
    return {"products": row[0], "stock": qty(row[1]), "reserved": qty(row[2]), "damaged": qty(row[3]), "low_stock": low}


# ---------------- purchases
class PurchaseIn(BaseModel):
    supplier_id: int
    product_id: int
    qty: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    purchase_date: Optional[date] = None
    supplier_bill_no: str = ""
    notes: str = ""
    update_product_cost: bool = True


@router.get("/purchases")
def list_purchases(date_from: Optional[str] = None, date_to: Optional[str] = None, supplier_id: Optional[int] = None,
                   page: Page = Depends(), db: Session = Depends(get_db),
                   _: User = Depends(require("purchases.manage", "costs.view"))):
    stmt = select(Purchase).where(Purchase.is_void.is_(False))
    if date_from:
        stmt = stmt.where(Purchase.purchase_date >= opt_date(date_from))
    if date_to:
        stmt = stmt.where(Purchase.purchase_date <= opt_date(date_to))
    if supplier_id:
        stmt = stmt.where(Purchase.supplier_id == supplier_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(Purchase.purchase_date.desc(), Purchase.id.desc()).offset(page.offset)
                      .limit(page.size)).unique().scalars().all()
    return paged([{"id": p.id, "supplier": p.supplier.name, "product": p.product.name,
                   "catalogue_no": p.product.catalogue_no, "factory_order_no": p.product.factory_order_no,
                   "qty": qty(p.qty), "unit_cost": money(p.unit_cost), "total": money(p.total),
                   "purchase_date": p.purchase_date.isoformat(), "supplier_bill_no": p.supplier_bill_no,
                   "notes": p.notes} for p in rows], total, page)


@router.post("/purchases")
def create_purchase(body: PurchaseIn, db: Session = Depends(get_db),
                    user: User = Depends(require("purchases.manage", "costs.view"))):
    if not db.get(Supplier, body.supplier_id):
        raise HTTPException(404, "Supplier not found.")
    try:
        p = lock_product(db, body.product_id)
        q, cost = d(body.qty, "0.001"), d(body.unit_cost)
        pu = Purchase(supplier_id=body.supplier_id, product_id=p.id, qty=q, unit_cost=cost, total=d(q * cost),
                      purchase_date=body.purchase_date or date.today(), supplier_bill_no=body.supplier_bill_no,
                      notes=body.notes, created_by=user.id)
        db.add(pu)
        db.flush()
        move_stock(db, p, "IN", q, user, "purchase", pu.id, f"Purchase {body.supplier_bill_no}".strip())
        if body.update_product_cost:
            p.purchase_cost = cost
        audit(db, user, "purchase_recorded", "purchase", pu.id, product=p.catalogue_no, qty=q, total=pu.total)
        db.commit()
    except BizError:
        db.rollback()
        raise
    return {"id": pu.id, "total": money(pu.total), "product": product_dict(p, user)}


# ---------------- expenses
class ExpenseIn(BaseModel):
    expense_date: Optional[date] = None
    category: str = Field(default="General", max_length=80)
    amount: Decimal = Field(gt=0)
    description: str = ""


@router.get("/expenses")
def list_expenses(date_from: Optional[str] = None, date_to: Optional[str] = None, page: Page = Depends(),
                  db: Session = Depends(get_db), _: User = Depends(require("expenses.manage"))):
    stmt = select(Expense).where(Expense.is_void.is_(False))
    if date_from:
        stmt = stmt.where(Expense.expense_date >= opt_date(date_from))
    if date_to:
        stmt = stmt.where(Expense.expense_date <= opt_date(date_to))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(Expense.expense_date.desc(), Expense.id.desc()).offset(page.offset)
                      .limit(page.size)).scalars().all()
    return paged([{"id": e.id, "expense_date": e.expense_date.isoformat(), "category": e.category,
                   "amount": money(e.amount), "description": e.description} for e in rows], total, page)


@router.post("/expenses")
def create_expense(body: ExpenseIn, db: Session = Depends(get_db), user: User = Depends(require("expenses.manage"))):
    e = Expense(expense_date=body.expense_date or date.today(), category=body.category.strip() or "General",
                amount=d(body.amount), description=body.description, created_by=user.id)
    db.add(e)
    db.flush()
    audit(db, user, "expense_recorded", "expense", e.id, amount=e.amount, category=e.category)
    db.commit()
    return {"id": e.id, "amount": money(e.amount)}


@router.post("/expenses/{expense_id}/void")
def void_expense(expense_id: int, db: Session = Depends(get_db), user: User = Depends(require("expenses.manage"))):
    e = db.get(Expense, expense_id)
    if not e or e.is_void:
        raise HTTPException(400, "Expense not found or already void.")
    e.is_void = True
    audit(db, user, "expense_voided", "expense", e.id, amount=e.amount)
    db.commit()
    return {"message": "Expense voided."}
