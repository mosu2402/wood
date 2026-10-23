"""All business rules live here so every screen and API uses the same logic."""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .models import (FACTORY_STATUSES, ZERO, AuditLog, Category, Counter, CreditNote, Customer,
                     FactoryOrder, FactoryOrderEvent, FactoryOrderLine, Invoice, InvoiceLine,
                     Payment, Product, ProductMappingHistory, StockMovement, Supplier, User, now)
from .types import d, money, qty


class BizError(Exception):
    """A business-rule violation with a message staff can understand."""

    def __init__(self, message: str, status: int = 400, extra: Optional[dict] = None):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra or {}


# --------------------------------------------------------------------------- helpers
_ws = re.compile(r"\s+")


def norm_no(value) -> str:
    """Normalise a product number for exact matching: trim, uppercase, drop inner spaces.
    Leading zeros are KEPT (0123 and 123 are different numbers). Excel floats like
    123.0 become 123."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    s = _ws.sub("", str(value)).upper()
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s


def norm_catalogue(value) -> str:
    s = _ws.sub(" ", str(value or "")).strip().upper()
    return s or "MAIN"


def next_number(db: Session, prefix: str, width: int = 6, yearly: bool = True) -> str:
    key = f"{prefix}-{date.today().year}" if yearly else prefix
    row = db.execute(select(Counter).where(Counter.name == key).with_for_update()).scalar_one_or_none()
    if row is None:
        row = Counter(name=key, value=0)
        db.add(row)
        db.flush()
    row.value += 1
    db.flush()
    return f"{key}-{row.value:0{width}d}"


def audit(db: Session, user: Optional[User], action: str, entity: str, entity_id=None, **details):
    clean = {k: (str(v) if isinstance(v, (Decimal, date, datetime)) else v) for k, v in details.items()}
    db.add(AuditLog(user_id=user.id if user else None, username=user.username if user else "system",
                    action=action, entity=entity, entity_id=entity_id, details=clean))


# --------------------------------------------------------------------------- stock
def lock_product(db: Session, product_id: int) -> Product:
    p = db.execute(select(Product).where(Product.id == product_id).with_for_update()).unique().scalar_one_or_none()
    if not p:
        raise BizError(f"Product id {product_id} not found.", 404)
    return p


def move_stock(db: Session, product: Product, kind: str, quantity, user: Optional[User],
               ref_type: str = "", ref_id: Optional[int] = None, note: str = "") -> StockMovement:
    q = d(quantity, "0.001")
    label = f"{product.name} (Cat. {product.catalogue_no})"
    if kind != "ADJUST" and q <= 0:
        raise BizError("Quantity must be more than zero.")
    avail = product.stock_qty - product.reserved_qty
    if kind in ("IN", "RETURN"):
        product.stock_qty += q
    elif kind == "OUT":
        if avail < q:
            raise BizError(f"Not enough stock for {label}. Available {qty(avail)}, needed {qty(q)}.",
                           extra={"product_id": product.id, "available": qty(avail)})
        product.stock_qty -= q
    elif kind == "OUT_RESERVED":  # issue goods that were reserved for an order
        if product.reserved_qty < q or product.stock_qty < q:
            raise BizError(f"Reserved stock for {label} is lower than {qty(q)}.")
        product.reserved_qty -= q
        product.stock_qty -= q
    elif kind == "DAMAGE":
        if avail < q:
            raise BizError(f"Only {qty(avail)} free stock of {label} can be marked damaged.")
        product.stock_qty -= q
        product.damaged_qty += q
    elif kind == "WRITE_OFF":
        if product.damaged_qty < q:
            raise BizError(f"Only {qty(product.damaged_qty)} damaged stock of {label} to write off.")
        product.damaged_qty -= q
    elif kind == "RESERVE":
        if avail < q:
            raise BizError(f"Only {qty(avail)} free stock of {label} can be reserved.")
        product.reserved_qty += q
    elif kind == "UNRESERVE":
        if product.reserved_qty < q:
            raise BizError(f"Only {qty(product.reserved_qty)} of {label} is reserved.")
        product.reserved_qty -= q
    elif kind == "ADJUST":
        new = product.stock_qty + q
        if new < 0:
            raise BizError("Stock cannot go below zero.")
        if new < product.reserved_qty:
            raise BizError(f"Stock cannot go below reserved quantity ({qty(product.reserved_qty)}).")
        product.stock_qty = new
    else:
        raise BizError(f"Unknown stock movement '{kind}'.")
    mv = StockMovement(product_id=product.id, kind=kind, qty=q, stock_after=product.stock_qty,
                       reserved_after=product.reserved_qty, ref_type=ref_type, ref_id=ref_id,
                       note=note[:255], user_id=user.id if user else None)
    db.add(mv)
    return mv


# --------------------------------------------------------------------------- product lookup
def lookup_by_catalogue_no(db: Session, number: str, catalogue: Optional[str] = None) -> dict:
    """The core rule: an exact catalogue number must resolve to exactly ONE product,
    otherwise return a warning instead of guessing."""
    n = norm_no(number)
    if not n:
        return {"status": "empty", "message": "Enter a catalogue number."}
    stmt = select(Product).where(Product.catalogue_no == n)
    if catalogue:
        stmt = stmt.where(Product.catalogue == norm_catalogue(catalogue))
    matches = db.execute(stmt).unique().scalars().all()
    active = [p for p in matches if p.is_active]
    if not matches:
        return {"status": "not_found",
                "message": f"No product has catalogue number {n}. Check the number in the customer's book."}
    if not active:
        return {"status": "inactive", "message": f"Catalogue number {n} belongs to a product that is switched off.",
                "matches": active or matches}
    if len(active) > 1:
        return {"status": "ambiguous",
                "message": f"Catalogue number {n} exists in {len(active)} catalogues. Pick the customer's catalogue.",
                "matches": active}
    p = active[0]
    if not p.factory_order_no:
        return {"status": "unmapped", "message": f"Catalogue number {n} has no factory number. Fix the mapping first.",
                "matches": [p]}
    return {"status": "ok", "product": p}


def change_mapping(db: Session, p: Product, user: Optional[User], catalogue: str, catalogue_no: str,
                   factory_order_no: str, supplier_id: int, reason: str = ""):
    catalogue, catalogue_no, factory_order_no = norm_catalogue(catalogue), norm_no(catalogue_no), norm_no(factory_order_no)
    if not catalogue_no or not factory_order_no:
        raise BizError("Both the catalogue number and the factory order number are required.")
    if (catalogue, catalogue_no, factory_order_no, supplier_id) == (p.catalogue, p.catalogue_no, p.factory_order_no, p.supplier_id):
        return False
    clash = db.execute(select(Product).where(Product.catalogue == catalogue, Product.catalogue_no == catalogue_no,
                                             Product.id != (p.id or 0))).unique().scalar_one_or_none()
    if clash:
        raise BizError(f"Catalogue number {catalogue_no} in catalogue {catalogue} already belongs to '{clash.name}'.", 409)
    clash = db.execute(select(Product).where(Product.supplier_id == supplier_id, Product.factory_order_no == factory_order_no,
                                             Product.id != (p.id or 0))).unique().scalar_one_or_none()
    if clash:
        raise BizError(f"Factory number {factory_order_no} is already mapped to catalogue number {clash.catalogue_no} ('{clash.name}').", 409)
    if p.id:
        db.add(ProductMappingHistory(product_id=p.id, old_catalogue=p.catalogue, old_catalogue_no=p.catalogue_no,
                                     old_factory_order_no=p.factory_order_no, old_supplier_id=p.supplier_id,
                                     new_catalogue=catalogue, new_catalogue_no=catalogue_no,
                                     new_factory_order_no=factory_order_no, new_supplier_id=supplier_id,
                                     reason=reason[:255], changed_by=user.id if user else None))
        audit(db, user, "mapping_changed", "product", p.id, old=f"{p.catalogue}/{p.catalogue_no}->{p.factory_order_no}",
              new=f"{catalogue}/{catalogue_no}->{factory_order_no}")
    p.catalogue, p.catalogue_no, p.factory_order_no, p.supplier_id = catalogue, catalogue_no, factory_order_no, supplier_id
    return True


def get_or_create_supplier(db: Session, name: str) -> Supplier:
    name = (name or "").strip() or "Default Factory"
    s = db.execute(select(Supplier).where(func.lower(Supplier.name) == name.lower())).scalar_one_or_none()
    if not s:
        s = Supplier(name=name)
        db.add(s)
        db.flush()
    return s


# --------------------------------------------------------------------------- billing
def calc_line(q: Decimal, rate: Decimal, disc_pct: Decimal, tax_rate: Decimal, cost_rate: Decimal) -> dict:
    gross = d(q * rate)
    disc = d(gross * disc_pct / 100)
    taxable = gross - disc
    tax = d(taxable * tax_rate / 100)
    if settings.GST_ROUND_RUPEE:
        tax = d(tax, "1").quantize(Decimal("0.01"))
    return {"gross": gross, "discount_amount": disc, "taxable": taxable, "tax_amount": tax,
            "line_total": taxable + tax, "cost_total": d(q * cost_rate)}


def apply_invoice_lines(db: Session, inv: Invoice, lines_in: list, user: User):
    """Create invoice lines, take stock out for STOCK lines and raise factory
    orders (grouped by supplier) for FACTORY lines."""
    if not lines_in:
        raise BizError("Add at least one product to the bill.")
    factory_lines: dict[int, list] = defaultdict(list)
    totals = defaultdict(lambda: ZERO)
    for i, li in enumerate(lines_in, 1):
        p = lock_product(db, li["product_id"])
        if not p.is_active:
            raise BizError(f"Line {i}: '{p.name}' is switched off and cannot be billed.")
        q = d(li["qty"], "0.001")
        if q <= 0:
            raise BizError(f"Line {i}: quantity must be more than zero.")
        rate = p.sale_price if li.get("rate") in (None, "") else d(li["rate"])
        if rate < 0:
            raise BizError(f"Line {i}: rate cannot be negative.")
        if rate != p.sale_price and not user.can("billing.override_price"):
            raise BizError(f"Line {i}: you are not allowed to change the rate of '{p.name}'.", 403)
        disc = d(li.get("discount_pct") or 0)
        if not (ZERO <= disc <= 100):
            raise BizError(f"Line {i}: discount must be between 0 and 100%.")
        fulfil = (li.get("fulfilment") or "STOCK").upper()
        if fulfil not in ("STOCK", "FACTORY"):
            raise BizError(f"Line {i}: choose 'From stock' or 'Order from factory'.")
        tax_rate = p.tax_rate if (inv.tax_mode or "BILL") == "BILL" else ZERO
        c = calc_line(q, rate, disc, tax_rate, p.purchase_cost)
        line = InvoiceLine(product_id=p.id, catalogue=p.catalogue, catalogue_no=p.catalogue_no,
                           factory_order_no=p.factory_order_no, product_name=p.name, brand=p.brand or "",
                           hsn=p.hsn or "", unit=p.unit, qty=q, rate=rate,
                           discount_pct=disc, tax_rate=tax_rate, cost_rate=p.purchase_cost, fulfilment=fulfil,
                           dimensions=(li.get("dimensions") or "")[:120], finish=(li.get("finish") or p.finish or "")[:100],
                           instructions=li.get("instructions") or "", **c)
        inv.lines.append(line)
        db.flush()
        for k in ("gross", "discount_amount", "taxable", "tax_amount", "line_total", "cost_total"):
            totals[k] += c[k]
        if fulfil == "STOCK":
            move_stock(db, p, "OUT", q, user, "invoice", inv.id, f"Bill {inv.number}")
        else:
            factory_lines[p.supplier_id].append((p, line))
    inv.subtotal, inv.discount_total = totals["gross"], totals["discount_amount"]
    inv.taxable_total, inv.tax_total = totals["taxable"], totals["tax_amount"]
    inv.total, inv.cost_total = totals["line_total"], totals["cost_total"]
    for supplier_id, items in factory_lines.items():
        fo = FactoryOrder(number=next_number(db, "FO"), customer_id=inv.customer_id, invoice_id=inv.id,
                          supplier_id=supplier_id, status="PENDING", notes=f"From bill {inv.number}",
                          created_by=user.id)
        for p, line in items:
            fo.lines.append(FactoryOrderLine(product_id=p.id, invoice_line_id=line.id, catalogue=p.catalogue,
                                             catalogue_no=p.catalogue_no, factory_order_no=p.factory_order_no,
                                             product_name=p.name, unit=p.unit, qty=line.qty, dimensions=line.dimensions,
                                             finish=line.finish, instructions=line.instructions))
        fo.events.append(FactoryOrderEvent(from_status="", to_status="PENDING", note=f"Created from bill {inv.number}",
                                           user_id=user.id))
        db.add(fo)
    db.flush()


def reverse_invoice_effects(db: Session, inv: Invoice, user: User, reason: str):
    orders = db.execute(select(FactoryOrder).where(FactoryOrder.invoice_id == inv.id,
                                                   FactoryOrder.status != "CANCELLED")).unique().scalars().all()
    for fo in orders:
        if fo.status not in ("PENDING", "APPROVED"):
            raise BizError(f"Factory order {fo.number} is already {fo.status.replace('_', ' ').lower()}. "
                           "Use a credit note instead of changing this bill.", 409)
    for fo in orders:
        set_factory_status(db, fo, "CANCELLED", user, f"Bill {inv.number} {reason}")
        for ln in fo.lines:  # keep the cancelled order readable after bill lines are replaced
            ln.invoice_line_id = None
    for line in inv.lines:
        if line.fulfilment == "STOCK":
            p = lock_product(db, line.product_id)
            move_stock(db, p, "RETURN", line.qty, user, "invoice", inv.id, f"Bill {inv.number} {reason}")


def invoice_settled(db: Session, invoice_id: int) -> dict:
    """Money settled against one invoice."""
    paid = db.scalar(select(func.coalesce(func.sum(case((Payment.kind == "PAYMENT", Payment.amount), else_=ZERO)), ZERO))
                     .where(Payment.invoice_id == invoice_id, Payment.is_void.is_(False))) or ZERO
    refunded = db.scalar(select(func.coalesce(func.sum(case((Payment.kind == "REFUND", Payment.amount), else_=ZERO)), ZERO))
                         .where(Payment.invoice_id == invoice_id, Payment.is_void.is_(False))) or ZERO
    credited = db.scalar(select(func.coalesce(func.sum(CreditNote.amount), ZERO))
                         .where(CreditNote.invoice_id == invoice_id, CreditNote.is_void.is_(False))) or ZERO
    paid, refunded, credited = d(paid), d(refunded), d(credited)
    return {"paid": paid, "refunded": refunded, "credited": credited, "settled": paid - refunded + credited}


def invoice_due(db: Session, inv: Invoice) -> Decimal:
    if inv.status == "CANCELLED":
        return ZERO
    return inv.total - invoice_settled(db, inv.id)["settled"]


def payment_status(total: Decimal, settled: Decimal, status: str) -> str:
    if status == "CANCELLED":
        return "CANCELLED"
    if settled >= total:
        return "PAID"
    return "PARTIAL" if settled > 0 else "UNPAID"


def settled_map(db: Session, invoice_ids: Iterable[int]) -> dict[int, Decimal]:
    ids = list(invoice_ids)
    out = {i: ZERO for i in ids}
    if not ids:
        return out
    for chunk_start in range(0, len(ids), 900):
        chunk = ids[chunk_start:chunk_start + 900]
        rows = db.execute(select(Payment.invoice_id, Payment.kind, func.sum(Payment.amount))
                          .where(Payment.invoice_id.in_(chunk), Payment.is_void.is_(False))
                          .group_by(Payment.invoice_id, Payment.kind)).all()
        for inv_id, kind, amt in rows:
            out[inv_id] += d(amt) if kind == "PAYMENT" else -d(amt)
        rows = db.execute(select(CreditNote.invoice_id, func.sum(CreditNote.amount))
                          .where(CreditNote.invoice_id.in_(chunk), CreditNote.is_void.is_(False))
                          .group_by(CreditNote.invoice_id)).all()
        for inv_id, amt in rows:
            out[inv_id] += d(amt)
    return out


# --------------------------------------------------------------------------- balances
def customer_totals(db: Session, customer_id: int, upto: Optional[date] = None, since: Optional[date] = None) -> dict:
    def _f(col, extra):
        conds = list(extra)
        if upto:
            conds.append(col <= upto)
        if since:
            conds.append(col >= since)
        return conds

    billed = db.scalar(select(func.coalesce(func.sum(Invoice.total), ZERO)).where(
        *_f(Invoice.invoice_date, [Invoice.customer_id == customer_id, Invoice.status == "ISSUED"]))) or ZERO
    paid = db.scalar(select(func.coalesce(func.sum(Payment.amount), ZERO)).where(
        *_f(Payment.paid_on, [Payment.customer_id == customer_id, Payment.kind == "PAYMENT", Payment.is_void.is_(False)]))) or ZERO
    refunded = db.scalar(select(func.coalesce(func.sum(Payment.amount), ZERO)).where(
        *_f(Payment.paid_on, [Payment.customer_id == customer_id, Payment.kind == "REFUND", Payment.is_void.is_(False)]))) or ZERO
    credited = db.scalar(select(func.coalesce(func.sum(CreditNote.amount), ZERO)).where(
        *_f(CreditNote.note_date, [CreditNote.customer_id == customer_id, CreditNote.is_void.is_(False)]))) or ZERO
    billed, paid, refunded, credited = d(billed), d(paid), d(refunded), d(credited)
    return {"billed": billed, "paid": paid, "refunded": refunded, "credited": credited,
            "outstanding": billed - paid + refunded - credited}


def outstanding_by_customer(db: Session, customer_id: Optional[int] = None) -> list[dict]:
    """Outstanding balance for every customer in a handful of grouped queries."""
    def grouped(stmt):
        return {cid: d(v) for cid, v in db.execute(stmt).all()}

    billed = grouped(select(Invoice.customer_id, func.sum(Invoice.total)).where(Invoice.status == "ISSUED")
                     .group_by(Invoice.customer_id))
    paid = grouped(select(Payment.customer_id, func.sum(Payment.amount)).where(
        Payment.kind == "PAYMENT", Payment.is_void.is_(False)).group_by(Payment.customer_id))
    refunded = grouped(select(Payment.customer_id, func.sum(Payment.amount)).where(
        Payment.kind == "REFUND", Payment.is_void.is_(False)).group_by(Payment.customer_id))
    credited = grouped(select(CreditNote.customer_id, func.sum(CreditNote.amount)).where(
        CreditNote.is_void.is_(False)).group_by(CreditNote.customer_id))
    ids = set(billed) | set(paid) | set(refunded) | set(credited)
    if customer_id:
        ids &= {customer_id}
    out = []
    for cid in ids:
        b, p, r, c = billed.get(cid, ZERO), paid.get(cid, ZERO), refunded.get(cid, ZERO), credited.get(cid, ZERO)
        out.append({"customer_id": cid, "billed": b, "paid": p, "refunded": r, "credited": c,
                    "outstanding": b - p + r - c})
    return out


def validate_payment(db: Session, customer_id: int, invoice_id: Optional[int], kind: str, amount: Decimal,
                     exclude_payment_id: Optional[int] = None):
    if amount <= 0:
        raise BizError("Amount must be more than zero.")
    if kind not in ("PAYMENT", "REFUND"):
        raise BizError("Choose payment or refund.")
    if invoice_id:
        inv = db.get(Invoice, invoice_id)
        if not inv or inv.customer_id != customer_id:
            raise BizError("That bill does not belong to this customer.", 400)
        if inv.status == "CANCELLED":
            raise BizError(f"Bill {inv.number} is cancelled.")
        s = invoice_settled(db, inv.id)
        if exclude_payment_id:
            old = db.get(Payment, exclude_payment_id)
            if old and not old.is_void and old.invoice_id == inv.id:
                s["settled"] -= old.amount if old.kind == "PAYMENT" else -old.amount
                if old.kind == "PAYMENT":
                    s["paid"] -= old.amount
                else:
                    s["refunded"] -= old.amount
        due = inv.total - s["settled"]
        if kind == "PAYMENT" and amount > due:
            raise BizError(f"Bill {inv.number} has only Rs. {money(due)} due. Record the extra "
                           f"Rs. {money(amount - due)} as an advance (without selecting a bill).",
                           extra={"due": money(due)})
        if kind == "REFUND" and amount > s["paid"] - s["refunded"]:
            raise BizError(f"Only Rs. {money(s['paid'] - s['refunded'])} was paid against bill {inv.number}.")
    elif kind == "REFUND":
        t = customer_totals(db, customer_id)
        credit = -t["outstanding"]
        if exclude_payment_id:
            old = db.get(Payment, exclude_payment_id)
            if old and not old.is_void:
                credit += old.amount if old.kind == "REFUND" else -old.amount
        if amount > credit:
            raise BizError(f"The customer has only Rs. {money(max(credit, ZERO))} credit available to refund.")


def find_possible_duplicate(db: Session, customer_id: int, amount: Decimal, method: str, reference: str,
                            paid_on: date) -> Optional[Payment]:
    if reference:
        dup = db.execute(select(Payment).where(Payment.customer_id == customer_id, Payment.method == method,
                                               Payment.reference == reference, Payment.is_void.is_(False))).unique().scalars().first()
        if dup:
            return dup
    since = now() - timedelta(minutes=10)
    return db.execute(select(Payment).where(Payment.customer_id == customer_id, Payment.amount == amount,
                                            Payment.method == method, Payment.paid_on == paid_on,
                                            Payment.is_void.is_(False), Payment.created_at >= since)).unique().scalars().first()


# --------------------------------------------------------------------------- factory orders
def _idx(s: str) -> int:
    return FACTORY_STATUSES.index(s)


def set_factory_status(db: Session, fo: FactoryOrder, new_status: str, user: User, note: str = ""):
    new_status = new_status.upper()
    if new_status not in FACTORY_STATUSES:
        raise BizError("Unknown status.")
    old = fo.status
    if old == new_status:
        return
    if old in ("DELIVERED", "CANCELLED"):
        raise BizError(f"Order {fo.number} is already {old.lower()} and cannot change.")
    if new_status == "CANCELLED":
        if fo.stock_issued:
            raise BizError("Goods are already dispatched. Record a return instead of cancelling.")
        if fo.stock_received and fo.customer_id:
            for ln in fo.lines:
                move_stock(db, lock_product(db, ln.product_id), "UNRESERVE", ln.qty, user, "factory_order", fo.id,
                           f"{fo.number} cancelled - goods kept in stock")
    else:
        if _idx(new_status) < _idx(old):
            raise BizError(f"Order cannot move back from {old.replace('_', ' ').lower()} to "
                           f"{new_status.replace('_', ' ').lower()}.")
        ready, dispatched = _idx("READY"), _idx("DISPATCHED")
        if not fo.stock_received and _idx(new_status) >= ready:
            for ln in fo.lines:
                p = lock_product(db, ln.product_id)
                move_stock(db, p, "IN", ln.qty, user, "factory_order", fo.id, f"Received {fo.number}")
                if fo.customer_id:
                    move_stock(db, p, "RESERVE", ln.qty, user, "factory_order", fo.id, f"Reserved for {fo.number}")
            fo.stock_received = True
        if fo.customer_id and not fo.stock_issued and _idx(new_status) >= dispatched:
            for ln in fo.lines:
                move_stock(db, lock_product(db, ln.product_id), "OUT_RESERVED", ln.qty, user, "factory_order", fo.id,
                           f"Dispatched {fo.number}")
            fo.stock_issued = True
        if _idx(new_status) >= dispatched and not fo.dispatched_at:
            fo.dispatched_at = now()
        if new_status == "DELIVERED":
            fo.delivered_at = now()
    fo.status = new_status
    fo.events.append(FactoryOrderEvent(from_status=old, to_status=new_status, note=note[:255], user_id=user.id))
    audit(db, user, "factory_status", "factory_order", fo.id, number=fo.number, old=old, new=new_status)


# --------------------------------------------------------------------------- serializers
def product_dict(p: Product, user: Optional[User] = None, minimal: bool = False) -> dict:
    show_cost = bool(user and user.can("costs.view"))
    out = {"id": p.id, "catalogue": p.catalogue, "catalogue_no": p.catalogue_no,
           "factory_order_no": p.factory_order_no, "name": p.name, "brand": p.brand or "", "hsn": p.hsn or "",
           "category": p.category.name if p.category else "", "category_id": p.category_id,
           "size": p.size, "finish": p.finish, "unit": p.unit, "sale_price": money(p.sale_price),
           "tax_rate": str(p.tax_rate), "stock_qty": qty(p.stock_qty), "reserved_qty": qty(p.reserved_qty),
           "available_qty": qty(p.available_qty), "damaged_qty": qty(p.damaged_qty),
           "reorder_level": qty(p.reorder_level), "is_active": p.is_active,
           "low_stock": p.reorder_level > 0 and p.available_qty <= p.reorder_level}
    if not minimal:
        out.update({"description": p.description, "updated_at": p.updated_at.isoformat() if p.updated_at else None})
    if show_cost:
        out.update({"purchase_cost": money(p.purchase_cost), "supplier_id": p.supplier_id,
                    "supplier": p.supplier.name if p.supplier else ""})
    return out


def invoice_dict(db: Session, inv: Invoice, user: Optional[User] = None, with_lines: bool = True,
                 settled: Optional[Decimal] = None) -> dict:
    is_customer = user is not None and user.role == "customer"
    show_cost = bool(user and user.can("costs.view"))
    if settled is None:
        settled = invoice_settled(db, inv.id)["settled"]
    out = {"id": inv.id, "number": inv.number, "customer_id": inv.customer_id,
           "customer_name": inv.customer.name if inv.customer else "", "invoice_date": inv.invoice_date.isoformat(),
           "source": inv.source, "tax_mode": inv.tax_mode or "BILL", "status": inv.status, "subtotal": money(inv.subtotal),
           "discount_total": money(inv.discount_total), "taxable_total": money(inv.taxable_total),
           "tax_total": money(inv.tax_total), "total": money(inv.total),
           "settled": money(settled), "due": money(ZERO if inv.status == "CANCELLED" else inv.total - settled),
           "payment_status": payment_status(inv.total, settled, inv.status),
           "delivery_status": inv.delivery_status, "notes": inv.notes, "cancel_reason": inv.cancel_reason,
           "created_at": inv.created_at.isoformat()}
    if show_cost:
        out["cost_total"] = money(inv.cost_total)
    if with_lines:
        lines = []
        for ln in inv.lines:
            row = {"id": ln.id, "product_id": ln.product_id, "catalogue": ln.catalogue, "catalogue_no": ln.catalogue_no,
                   "product_name": ln.product_name, "brand": ln.brand or "", "hsn": ln.hsn or "", "unit": ln.unit, "qty": qty(ln.qty), "rate": money(ln.rate),
                   "discount_pct": str(ln.discount_pct), "tax_rate": str(ln.tax_rate), "gross": money(ln.gross),
                   "discount_amount": money(ln.discount_amount), "taxable": money(ln.taxable),
                   "tax_amount": money(ln.tax_amount), "line_total": money(ln.line_total),
                   "fulfilment": ln.fulfilment, "dimensions": ln.dimensions, "finish": ln.finish,
                   "instructions": ln.instructions}
            if not is_customer:
                row["factory_order_no"] = ln.factory_order_no
            if show_cost:
                row["cost_total"] = money(ln.cost_total)
            lines.append(row)
        out["lines"] = lines
    return out


def payment_dict(p: Payment, invoice_number: str = "") -> dict:
    return {"id": p.id, "number": p.number, "customer_id": p.customer_id,
            "customer_name": p.customer.name if p.customer else "", "invoice_id": p.invoice_id,
            "invoice_number": invoice_number, "kind": p.kind, "amount": money(p.amount), "method": p.method,
            "reference": p.reference, "paid_on": p.paid_on.isoformat(), "notes": p.notes, "is_void": p.is_void,
            "void_reason": p.void_reason, "created_at": p.created_at.isoformat()}


def factory_dict(fo: FactoryOrder, user: Optional[User] = None) -> dict:
    is_customer = user is not None and user.role == "customer"
    out = {"id": fo.id, "number": fo.number, "customer_id": fo.customer_id,
           "customer_name": fo.customer.name if fo.customer else "(Stock order)", "invoice_id": fo.invoice_id,
           "status": fo.status, "expected_date": fo.expected_date.isoformat() if fo.expected_date else None,
           "notes": "" if is_customer else fo.notes, "created_at": fo.created_at.isoformat(),
           "dispatched_at": fo.dispatched_at.isoformat() if fo.dispatched_at else None,
           "delivered_at": fo.delivered_at.isoformat() if fo.delivered_at else None,
           "lines": [{"product_id": ln.product_id, "catalogue": ln.catalogue, "catalogue_no": ln.catalogue_no,
                      "product_name": ln.product_name, "qty": qty(ln.qty), "unit": ln.unit,
                      "dimensions": ln.dimensions, "finish": ln.finish, "instructions": ln.instructions,
                      **({} if is_customer else {"factory_order_no": ln.factory_order_no})} for ln in fo.lines]}
    if not is_customer:
        out["supplier"] = fo.supplier.name if fo.supplier else ""
        out["supplier_id"] = fo.supplier_id
        out["events"] = [{"from": e.from_status, "to": e.to_status, "note": e.note,
                          "at": e.created_at.isoformat()} for e in fo.events]
    return out


def customer_dict(c: Customer) -> dict:
    return {"id": c.id, "code": c.code, "name": c.name, "phone": c.phone, "area": c.area or "", "email": c.email,
            "address": c.address, "gstin": c.gstin, "notes": c.notes, "is_active": c.is_active,
            "created_at": c.created_at.isoformat()}


def customer_account(db: Session, customer_id: int, user: User) -> dict:
    c = db.get(Customer, customer_id)
    if not c:
        raise BizError("Customer not found.", 404)
    invoices = db.execute(select(Invoice).where(Invoice.customer_id == c.id)
                          .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())).unique().scalars().all()
    smap = settled_map(db, [i.id for i in invoices])
    inv_numbers = {i.id: i.number for i in invoices}
    payments = db.execute(select(Payment).where(Payment.customer_id == c.id)
                          .order_by(Payment.paid_on.desc(), Payment.id.desc())).unique().scalars().all()
    notes = db.execute(select(CreditNote).where(CreditNote.customer_id == c.id)
                       .order_by(CreditNote.note_date.desc())).scalars().all()
    orders = db.execute(select(FactoryOrder).where(FactoryOrder.customer_id == c.id)
                        .order_by(FactoryOrder.id.desc())).unique().scalars().all()
    is_customer = user.role == "customer"
    t = customer_totals(db, c.id)
    pids = {ln.product_id for i in invoices for ln in i.lines}
    cat_of = {}
    if pids:
        for pid, cname in db.execute(select(Product.id, Category.name).outerjoin(Category, Category.id == Product.category_id)
                                     .where(Product.id.in_(pids))).all():
            cat_of[pid] = cname or ""
    inv_out = []
    for i in invoices:
        x = invoice_dict(db, i, user, with_lines=True, settled=smap[i.id])
        for ln in x["lines"]:
            ln["category"] = cat_of.get(ln["product_id"], "")
        inv_out.append(x)
    return {
        "customer": customer_dict(c),
        "totals": {k: money(v) for k, v in t.items()},
        "invoices": inv_out,
        "payments": [payment_dict(p, inv_numbers.get(p.invoice_id, "")) for p in payments
                     if not (is_customer and p.is_void)],
        "credit_notes": [{"id": n.id, "number": n.number, "invoice_id": n.invoice_id,
                          "invoice_number": inv_numbers.get(n.invoice_id, ""), "amount": money(n.amount),
                          "reason": n.reason, "note_date": n.note_date.isoformat(), "is_void": n.is_void}
                         for n in notes if not (is_customer and n.is_void)],
        "orders": [factory_dict(o, user) for o in orders],
    }


def statement_entries(db: Session, customer_id: int, since: Optional[date], upto: Optional[date]) -> dict:
    """Running-balance ledger for statements."""
    opening = ZERO
    if since:
        opening = customer_totals(db, customer_id, upto=since - timedelta(days=1))["outstanding"]
    entries = []
    q = select(Invoice).where(Invoice.customer_id == customer_id, Invoice.status == "ISSUED")
    if since:
        q = q.where(Invoice.invoice_date >= since)
    if upto:
        q = q.where(Invoice.invoice_date <= upto)
    for inv in db.execute(q).unique().scalars():
        entries.append((inv.invoice_date, 0, inv.id, f"Bill {inv.number}", inv.total, ZERO))
    q = select(Payment).where(Payment.customer_id == customer_id, Payment.is_void.is_(False))
    if since:
        q = q.where(Payment.paid_on >= since)
    if upto:
        q = q.where(Payment.paid_on <= upto)
    for p in db.execute(q).unique().scalars():
        ref = f" ({p.reference})" if p.reference else ""
        if p.kind == "PAYMENT":
            entries.append((p.paid_on, 1, p.id, f"Payment {p.number} - {p.method}{ref}", ZERO, p.amount))
        else:
            entries.append((p.paid_on, 1, p.id, f"Refund {p.number} - {p.method}{ref}", p.amount, ZERO))
    q = select(CreditNote).where(CreditNote.customer_id == customer_id, CreditNote.is_void.is_(False))
    if since:
        q = q.where(CreditNote.note_date >= since)
    if upto:
        q = q.where(CreditNote.note_date <= upto)
    for n in db.execute(q).scalars():
        entries.append((n.note_date, 2, n.id, f"Credit note {n.number} {n.reason}".strip(), ZERO, n.amount))
    entries.sort(key=lambda e: (e[0], e[1], e[2]))
    bal = opening
    rows = []
    for dt, _o, _i, text, debit, credit in entries:
        bal += debit - credit
        rows.append({"date": dt.isoformat(), "particulars": text, "debit": money(debit),
                     "credit": money(credit), "balance": money(bal)})
    return {"opening": money(opening), "closing": money(bal), "rows": rows}
