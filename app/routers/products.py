import csv
import io
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import Page, file_response, paged
from ..models import Category, Product, ProductMappingHistory, StockMovement, Supplier, User
from ..security import require, require_any
from ..services import (BizError, audit, change_mapping, get_or_create_supplier, lookup_by_catalogue_no, move_stock,
                        norm_catalogue, norm_no, product_dict)
from ..types import d, money, qty

router = APIRouter(prefix="/api", tags=["products"])
can_view = require_any("products.view", "billing.create", "factory.manage", "products.edit")


def _search_stmt(q: str, category_id, catalogue, low_stock, active):
    stmt = select(Product)
    if q:
        n = norm_no(q)
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Product.catalogue_no == n, Product.factory_order_no == n,
                              Product.catalogue_no.like(f"{n}%"), Product.factory_order_no.like(f"{n}%"),
                              Product.name.ilike(like), Product.brand.ilike(like)))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if catalogue:
        stmt = stmt.where(Product.catalogue == norm_catalogue(catalogue))
    if active is not None:
        stmt = stmt.where(Product.is_active.is_(active))
    if low_stock:
        stmt = stmt.where(Product.reorder_level > 0, Product.stock_qty - Product.reserved_qty <= Product.reorder_level)
    return stmt


@router.get("/products")
def list_products(q: str = "", category_id: Optional[int] = None, catalogue: str = "", low_stock: bool = False,
                  active: Optional[bool] = None, page: Page = Depends(), db: Session = Depends(get_db),
                  user: User = Depends(can_view)):
    stmt = _search_stmt(q, category_id, catalogue, low_stock, active)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    order = []
    if q:
        n = norm_no(q)
        order.append(case((Product.catalogue_no == n, 0), (Product.factory_order_no == n, 1), else_=2))
    rows = db.execute(stmt.order_by(*order, Product.catalogue, Product.catalogue_no).offset(page.offset)
                      .limit(page.size)).unique().scalars().all()
    return paged([product_dict(p, user, minimal=True) for p in rows], total, page)


@router.get("/products/lookup")
def lookup(catalogue_no: str, catalogue: str = "", db: Session = Depends(get_db), user: User = Depends(can_view)):
    """Customer catalogue number -> exactly one product + its factory order number."""
    r = lookup_by_catalogue_no(db, catalogue_no, catalogue or None)
    out = {"status": r["status"], "message": r.get("message", "")}
    if r["status"] == "ok":
        out["product"] = product_dict(r["product"], user)
    if r.get("matches"):
        out["matches"] = [product_dict(p, user, minimal=True) for p in r["matches"]]
    return out


@router.get("/products/catalogues")
def catalogues(db: Session = Depends(get_db), _: User = Depends(can_view)):
    return [c for (c,) in db.execute(select(Product.catalogue).distinct().order_by(Product.catalogue))]


@router.get("/products/check-duplicates")
def duplicates(db: Session = Depends(get_db), _: User = Depends(require("products.edit"))):
    """Catalogue numbers that exist in more than one catalogue (need the catalogue chosen at billing)."""
    rows = db.execute(select(Product.catalogue_no, func.count()).where(Product.is_active.is_(True))
                      .group_by(Product.catalogue_no).having(func.count() > 1).limit(500)).all()
    return [{"catalogue_no": n, "count": c} for n, c in rows]


class ProductIn(BaseModel):
    catalogue: str = "MAIN"
    catalogue_no: str = Field(min_length=1, max_length=60)
    factory_order_no: str = Field(min_length=1, max_length=60)
    supplier_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=200)
    brand: str = Field(default="", max_length=80)
    hsn: str = Field(default="", max_length=20)
    category_id: Optional[int] = None
    description: str = ""
    size: str = ""
    finish: str = ""
    unit: str = "pcs"
    sale_price: Decimal = Field(ge=0)
    purchase_cost: Decimal = Field(default=Decimal(0), ge=0)
    tax_rate: Decimal = Field(default=Decimal(18), ge=0, le=100)
    opening_stock: Decimal = Field(default=Decimal(0), ge=0)
    reorder_level: Decimal = Field(default=Decimal(0), ge=0)
    is_active: bool = True
    mapping_change_reason: str = ""


@router.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), user: User = Depends(can_view)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    out = product_dict(p, user)
    out["mapping_history"] = [
        {"old": f"{h.old_catalogue} / {h.old_catalogue_no} -> {h.old_factory_order_no}",
         "new": f"{h.new_catalogue} / {h.new_catalogue_no} -> {h.new_factory_order_no}",
         "reason": h.reason, "changed_at": h.changed_at.isoformat()}
        for h in db.execute(select(ProductMappingHistory).where(ProductMappingHistory.product_id == p.id)
                            .order_by(ProductMappingHistory.id.desc())).scalars()]
    out["movements"] = [
        {"kind": m.kind, "qty": qty(m.qty), "stock_after": qty(m.stock_after), "note": m.note,
         "ref_type": m.ref_type, "ref_id": m.ref_id, "at": m.created_at.isoformat()}
        for m in db.execute(select(StockMovement).where(StockMovement.product_id == p.id)
                            .order_by(StockMovement.id.desc()).limit(100)).scalars()]
    return out


@router.post("/products")
def create_product(body: ProductIn, db: Session = Depends(get_db), user: User = Depends(require("products.edit"))):
    supplier_id = body.supplier_id if (body.supplier_id and user.can("costs.view")) else get_or_create_supplier(db, "").id
    if body.category_id and not db.get(Category, body.category_id):
        raise HTTPException(400, "Category not found.")
    p = Product(name=body.name.strip(), brand=body.brand.strip(), hsn=body.hsn.strip(), category_id=body.category_id, description=body.description,
                size=body.size, finish=body.finish, unit=body.unit or "pcs", sale_price=d(body.sale_price),
                purchase_cost=d(body.purchase_cost) if user.can("costs.view") else Decimal(0),
                tax_rate=d(body.tax_rate), stock_qty=Decimal(0), reserved_qty=Decimal(0), damaged_qty=Decimal(0),
                reorder_level=d(body.reorder_level, "0.001"), is_active=body.is_active,
                catalogue="", catalogue_no="", factory_order_no="", supplier_id=supplier_id)
    change_mapping(db, p, user, body.catalogue, body.catalogue_no, body.factory_order_no, supplier_id)
    db.add(p)
    db.flush()
    if body.opening_stock > 0:
        move_stock(db, p, "IN", body.opening_stock, user, "product", p.id, "Opening stock")
    audit(db, user, "product_created", "product", p.id, catalogue_no=p.catalogue_no, factory_no=p.factory_order_no)
    db.commit()
    return product_dict(p, user)


@router.put("/products/{product_id}")
def update_product(product_id: int, body: ProductIn, db: Session = Depends(get_db),
                   user: User = Depends(require("products.edit"))):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    supplier_id = body.supplier_id if (body.supplier_id and user.can("costs.view")) else p.supplier_id
    change_mapping(db, p, user, body.catalogue, body.catalogue_no, body.factory_order_no, supplier_id,
                   body.mapping_change_reason)
    before = {"sale_price": money(p.sale_price), "name": p.name}
    p.name, p.category_id, p.description = body.name.strip(), body.category_id, body.description
    p.brand, p.hsn = body.brand.strip(), body.hsn.strip()
    p.size, p.finish, p.unit = body.size, body.finish, body.unit or "pcs"
    p.sale_price, p.tax_rate = d(body.sale_price), d(body.tax_rate)
    p.reorder_level, p.is_active = d(body.reorder_level, "0.001"), body.is_active
    if user.can("costs.view"):
        p.purchase_cost = d(body.purchase_cost)
    audit(db, user, "product_updated", "product", p.id, before=before,
          after={"sale_price": money(p.sale_price), "name": p.name})
    db.commit()
    return product_dict(p, user)


@router.get("/products-export")
def export_products(fmt: str = Query("xlsx", pattern="^(xlsx|csv)$"), q: str = "", category_id: Optional[int] = None,
                    db: Session = Depends(get_db), user: User = Depends(require("products.view"))):
    show_cost = user.can("costs.view")
    head = ["catalogue", "catalogue_no", "factory_order_no", "name", "brand", "hsn", "category", "description", "size", "finish",
            "unit", "sale_price", "tax_rate", "quantity", "reserved", "damaged", "reorder_level"]
    if show_cost:
        head += ["purchase_cost", "supplier"]
    stmt = _search_stmt(q, category_id, "", False, None).order_by(Product.catalogue, Product.catalogue_no)

    def rows():
        for p in db.execute(stmt.execution_options(yield_per=2000)).scalars():
            r = [p.catalogue, p.catalogue_no, p.factory_order_no, p.name, p.brand, p.hsn, p.category.name if p.category else "",
                 p.description, p.size, p.finish, p.unit, float(p.sale_price), float(p.tax_rate), float(p.stock_qty),
                 float(p.reserved_qty), float(p.damaged_qty), float(p.reorder_level)]
            if show_cost:
                r += [float(p.purchase_cost), p.supplier.name if p.supplier else ""]
            yield r

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(head)
        w.writerows(rows())
        return file_response(buf.getvalue().encode("utf-8-sig"), "products.csv", "text/csv")
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Products")
    ws.append(head)
    for r in rows():
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return file_response(buf.getvalue(), "products.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------- categories
class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_active: bool = True


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), _: User = Depends(can_view)):
    counts = dict(db.execute(select(Product.category_id, func.count()).group_by(Product.category_id)).all())
    return [{"id": c.id, "name": c.name, "is_active": c.is_active, "products": counts.get(c.id, 0)}
            for c in db.execute(select(Category).order_by(Category.name)).scalars()]


@router.post("/categories")
def create_category(body: CategoryIn, db: Session = Depends(get_db), user: User = Depends(require("products.edit"))):
    if db.execute(select(Category).where(func.lower(Category.name) == body.name.strip().lower())).scalar_one_or_none():
        raise HTTPException(409, "That category already exists.")
    c = Category(name=body.name.strip(), is_active=body.is_active)
    db.add(c)
    db.flush()
    audit(db, user, "category_created", "category", c.id, name=c.name)
    db.commit()
    return {"id": c.id, "name": c.name, "is_active": c.is_active}


@router.put("/categories/{cid}")
def update_category(cid: int, body: CategoryIn, db: Session = Depends(get_db), user: User = Depends(require("products.edit"))):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Category not found.")
    c.name, c.is_active = body.name.strip(), body.is_active
    audit(db, user, "category_updated", "category", c.id, name=c.name)
    db.commit()
    return {"id": c.id, "name": c.name, "is_active": c.is_active}


# ---------------- suppliers (confidential: costs.view)
class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    phone: str = ""
    email: str = ""
    address: str = ""
    notes: str = ""


def _sup(s: Supplier) -> dict:
    return {"id": s.id, "name": s.name, "phone": s.phone, "email": s.email, "address": s.address, "notes": s.notes}


@router.get("/suppliers")
def list_suppliers(db: Session = Depends(get_db), _: User = Depends(require_any("costs.view", "factory.manage", "purchases.manage"))):
    return [_sup(s) for s in db.execute(select(Supplier).order_by(Supplier.name)).scalars()]


@router.post("/suppliers")
def create_supplier(body: SupplierIn, db: Session = Depends(get_db), user: User = Depends(require("costs.view"))):
    if db.execute(select(Supplier).where(func.lower(Supplier.name) == body.name.strip().lower())).scalar_one_or_none():
        raise HTTPException(409, "That supplier already exists.")
    s = Supplier(**{**body.model_dump(), "name": body.name.strip()})
    db.add(s)
    db.flush()
    audit(db, user, "supplier_created", "supplier", s.id, name=s.name)
    db.commit()
    return _sup(s)


@router.put("/suppliers/{sid}")
def update_supplier(sid: int, body: SupplierIn, db: Session = Depends(get_db), user: User = Depends(require("costs.view"))):
    s = db.get(Supplier, sid)
    if not s:
        raise HTTPException(404, "Supplier not found.")
    for k, v in body.model_dump().items():
        setattr(s, k, v.strip() if k == "name" else v)
    audit(db, user, "supplier_updated", "supplier", s.id, name=s.name)
    db.commit()
    return _sup(s)
