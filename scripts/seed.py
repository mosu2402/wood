"""Load sample data.
    python -m scripts.seed               -> demo data (owner/staff/customer logins, 300 products, bills)
    python -m scripts.seed --products 100000   -> also generate a large inventory for speed testing
    python -m scripts.seed --excel sample_inventory.xlsx --products 5000  -> write a sample import file only"""
import argparse
import random
from datetime import date, timedelta
from decimal import Decimal

from openpyxl import Workbook
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Category, Customer, Product, StockMovement, Supplier, User
from app.security import hash_password
from app.services import apply_invoice_lines, next_number, set_factory_status
from app.models import FactoryOrder, Invoice, Payment

CATS = {"Laminates": ("sheet", ["Suede", "Gloss", "Matt", "Textured", "Woodgrain"], (900, 3200), "8x4 ft"),
        "Wooden Doors": ("pcs", ["Teak", "Walnut", "Oak", "Natural"], (6500, 28000), "7x3 ft"),
        "Decorative Panels": ("pcs", ["Fluted", "Charcoal", "Marble", "Metallic"], (1200, 6500), "9x1 ft"),
        "Veneers": ("sheet", ["Natural", "Smoked", "Recon"], (2500, 9500), "8x4 ft"),
        "Hardware & Adhesives": ("pcs", ["Steel", "Brass", "Matt Black"], (80, 1800), "")}
WORDS = ["Royal", "Urban", "Classic", "Nordic", "Imperial", "Sahara", "Amber", "Ivory", "Slate", "Coastal",
         "Heritage", "Luxe", "Prime", "Elite", "Majestic"]


def gen_rows(n, start=1):
    rnd = random.Random(42)
    names = list(CATS)
    for i in range(start, start + n):
        cat = names[i % len(names)]
        unit, finishes, (lo, hi), size = CATS[cat]
        price = Decimal(rnd.randrange(lo, hi, 10))
        yield {"catalogue": "MAIN", "catalogue_no": str(1000 + i), "factory_order_no": f"F{700000 + i * 7}",
               "name": f"{rnd.choice(WORDS)} {rnd.choice(finishes)} {cat.rstrip('s')} {i}", "category": cat,
               "size": size, "finish": rnd.choice(finishes), "unit": unit, "sale_price": price,
               "purchase_cost": (price * Decimal("0.68")).quantize(Decimal("1")), "tax_rate": Decimal(18),
               "quantity": Decimal(rnd.randrange(0, 200)), "reorder_level": Decimal(rnd.choice([0, 5, 10, 20]))}


def write_excel(path, n):
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Products")
    head = ["catalogue", "catalogue_no", "factory_order_no", "name", "category", "size", "finish", "unit",
            "sale_price", "purchase_cost", "tax_rate", "quantity", "reorder_level"]
    ws.append(head)
    for r in gen_rows(n):
        ws.append([str(r[h]) if isinstance(r[h], Decimal) else r[h] for h in head])
    wb.save(path)
    print("Wrote", path)


def bulk_products(db, n):
    sup = db.execute(select(Supplier).where(Supplier.name == "Default Factory")).scalar_one_or_none() or Supplier(name="Default Factory")
    db.add(sup)
    db.flush()
    cats = {}
    for c in CATS:
        cats[c] = db.execute(select(Category).where(Category.name == c)).scalar_one_or_none() or Category(name=c)
        db.add(cats[c])
    db.flush()
    start = (db.scalar(select(func.count(Product.id))) or 0) + 1
    batch = []
    for r in gen_rows(n, start):
        batch.append(Product(catalogue=r["catalogue"], catalogue_no=r["catalogue_no"], factory_order_no=r["factory_order_no"],
                             supplier_id=sup.id, name=r["name"], category_id=cats[r["category"]].id, size=r["size"],
                             finish=r["finish"], unit=r["unit"], sale_price=r["sale_price"],
                             purchase_cost=r["purchase_cost"], tax_rate=r["tax_rate"], stock_qty=r["quantity"],
                             reserved_qty=Decimal(0), damaged_qty=Decimal(0), reorder_level=r["reorder_level"]))
        if len(batch) == 5000:
            _flush(db, batch)
            batch = []
    _flush(db, batch)
    db.commit()
    print(f"Added {n} products.")


def _flush(db, batch):
    if not batch:
        return
    db.add_all(batch)
    db.flush()
    db.add_all([StockMovement(product_id=p.id, kind="IN", qty=p.stock_qty, stock_after=p.stock_qty,
                              reserved_after=Decimal(0), ref_type="seed", note="Opening stock")
                for p in batch if p.stock_qty > 0])
    db.flush()


def demo(db):
    if db.scalar(select(func.count(User.id))):
        print("Users already exist; skipping demo users.")
    else:
        db.add(User(username="owner", full_name="Shop Owner", password_hash=hash_password("owner123"), role="owner"))
        db.add(User(username="staff", full_name="Counter Staff", password_hash=hash_password("staff123"), role="staff",
                    permissions=["products.view", "customers.view", "customers.edit", "billing.create",
                                 "payments.record", "factory.manage", "stock.manage", "reports.view"]))
        db.flush()
    if not db.scalar(select(func.count(Product.id))):
        bulk_products(db, 300)
        sup = db.execute(select(Supplier).where(Supplier.name == "Default Factory")).scalar_one()
        doors = db.execute(select(Category).where(Category.name == "Wooden Doors")).scalar_one()
        db.add(Product(catalogue="MAIN", catalogue_no="123", factory_order_no="789", supplier_id=sup.id,
                       name="Teak Flush Door", category_id=doors.id, size="7x3 ft", finish="Teak", unit="pcs",
                       sale_price=Decimal(8500), purchase_cost=Decimal(6200), tax_rate=Decimal(18),
                       stock_qty=Decimal(10), reserved_qty=Decimal(0), damaged_qty=Decimal(0), reorder_level=Decimal(3)))
        db.commit()
    if not db.scalar(select(func.count(Customer.id))):
        owner = db.execute(select(User).where(User.role == "owner")).scalars().first()
        rnd = random.Random(7)
        people = ["Sharma Interiors", "Patel Furniture", "Mehta Constructions", "Rao Home Decor", "Gupta Builders",
                  "Iyer Residence", "Khan Woodworks", "Desai Architects", "Joshi Villas", "Shah Modular Kitchens"]
        custs = []
        for i, name in enumerate(people):
            c = Customer(code=next_number(db, "C", width=5, yearly=False), name=name,
                         phone=f"98{rnd.randrange(10000000, 99999999)}", address=f"{i + 1} Market Road")
            db.add(c)
            custs.append(c)
        db.flush()
        prods = db.execute(select(Product).where(Product.stock_qty > 20).limit(60)).unique().scalars().all()
        for k in range(25):
            c = custs[k % len(custs)]
            inv = Invoice(number=next_number(db, "INV"), customer_id=c.id,
                          invoice_date=date.today() - timedelta(days=rnd.randrange(0, 40)), created_by=owner.id)
            db.add(inv)
            db.flush()
            lines = [{"product_id": p.id, "qty": rnd.randrange(1, 5), "discount_pct": rnd.choice([0, 0, 5, 10])}
                     for p in rnd.sample(prods, 3)]
            if k % 6 == 0:
                lines.append({"product_id": prods[0].id, "qty": 2, "fulfilment": "FACTORY", "dimensions": "7ft x 3ft",
                              "instructions": "Pre-hung frame"})
            apply_invoice_lines(db, inv, lines, owner)
            if k % 3 != 2:
                share = Decimal(rnd.choice([1, 1, Decimal("0.5"), Decimal("0.3")]))
                db.add(Payment(number=next_number(db, "PAY"), customer_id=c.id, invoice_id=inv.id, kind="PAYMENT",
                               amount=(inv.total * share).quantize(Decimal("0.01")), method=rnd.choice(["CASH", "UPI", "BANK"]),
                               paid_on=inv.invoice_date, created_by=owner.id))
        db.flush()
        for fo in db.execute(select(FactoryOrder)).unique().scalars().all()[:2]:
            set_factory_status(db, fo, "SENT_TO_FACTORY", owner, "Demo")
        db.add(User(username="sharma", full_name="Sharma Interiors", password_hash=hash_password("cust123"),
                    role="customer", customer_id=custs[0].id))
        db.commit()
    print("Demo data ready. Logins: owner/owner123, staff/staff123, sharma/cust123 (customer).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--products", type=int, default=0)
    ap.add_argument("--excel", default="")
    a = ap.parse_args()
    if a.excel:
        write_excel(a.excel, a.products or 1000)
    else:
        s = SessionLocal()
        demo(s)
        if a.products:
            bulk_products(s, a.products)
