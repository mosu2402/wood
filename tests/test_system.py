import io
from decimal import Decimal

from openpyxl import Workbook

from .conftest import login


def D(x):
    return Decimal(str(x))


# ---------------------------------------------------------------- mapping
def test_catalogue_to_factory_lookup(client, owner, setup):
    r = client.get("/api/products/lookup", params={"catalogue_no": "123"}, headers=owner).json()
    assert r["status"] == "ok"
    assert r["product"]["factory_order_no"] == "789"
    assert r["product"]["name"] == "Teak Flush Door"
    # whitespace / case tolerant, but exact
    assert client.get("/api/products/lookup", params={"catalogue_no": " l-55 "}, headers=owner).json()["product"]["factory_order_no"] == "FX-9001"
    # leading zeros are a different number
    assert client.get("/api/products/lookup", params={"catalogue_no": "0123"}, headers=owner).json()["product"]["factory_order_no"] == "Z-1"
    # partial numbers never match
    assert client.get("/api/products/lookup", params={"catalogue_no": "12"}, headers=owner).json()["status"] == "not_found"


def test_duplicate_numbers_rejected_and_ambiguity_warned(client, owner, setup):
    dup = client.post("/api/products", headers=owner, json={"catalogue_no": "123", "factory_order_no": "999",
                                                             "name": "Dup", "sale_price": "1"})
    assert dup.status_code == 409
    dup_f = client.post("/api/products", headers=owner, json={"catalogue_no": "124", "factory_order_no": "789",
                                                               "name": "Dup", "sale_price": "1"})
    assert dup_f.status_code == 409 and "789" in dup_f.json()["detail"]
    # same catalogue number in a second catalogue book -> lookup must ask which one
    r = client.post("/api/products", headers=owner, json={"catalogue": "Premium Book", "catalogue_no": "L-55",
                                                           "factory_order_no": "PX-1", "name": "Premium L55",
                                                           "sale_price": "300"})
    assert r.status_code == 200
    look = client.get("/api/products/lookup", params={"catalogue_no": "L-55"}, headers=owner).json()
    assert look["status"] == "ambiguous" and len(look["matches"]) == 2
    look = client.get("/api/products/lookup", params={"catalogue_no": "L-55", "catalogue": "premium book"},
                      headers=owner).json()
    assert look["status"] == "ok" and look["product"]["factory_order_no"] == "PX-1"


# ---------------------------------------------------------------- billing
def test_bill_calculation_stock_and_factory_order(client, owner, setup):
    door, lam, a = setup["door"], setup["lam"], setup["a"]
    body = {"customer_id": a["id"], "lines": [
        {"product_id": lam["id"], "qty": "3", "discount_pct": "10"},
        {"product_id": door["id"], "qty": "2", "fulfilment": "FACTORY", "dimensions": "7ft x 3ft",
         "instructions": "Pre-hung"}]}
    r = client.post("/api/invoices", headers=owner, json=body)
    assert r.status_code == 200, r.text
    inv = r.json()
    # laminate: 3*250=750, -10% = 675, +18% = 121.50 -> 796.50 ; door: 2000 +360 = 2360
    assert D(inv["subtotal"]) == D("2750.00")
    assert D(inv["discount_total"]) == D("75.00")
    assert D(inv["tax_total"]) == D("481.50")
    assert D(inv["total"]) == D("3156.50")
    assert inv["payment_status"] == "UNPAID"
    door_line = [l for l in inv["lines"] if l["product_name"] == "Teak Flush Door"][0]
    assert door_line["catalogue_no"] == "123" and door_line["factory_order_no"] == "789"
    # stock line deducted, factory line not
    assert D(client.get(f"/api/products/{lam['id']}", headers=owner).json()["stock_qty"]) == 97
    assert D(client.get(f"/api/products/{door['id']}", headers=owner).json()["stock_qty"]) == 10
    fo = inv["factory_orders"][0]
    assert fo["status"] == "PENDING" and fo["lines"][0]["factory_order_no"] == "789"
    assert fo["lines"][0]["catalogue_no"] == "123" and fo["lines"][0]["dimensions"] == "7ft x 3ft"
    setup["inv1"] = inv


def test_insufficient_stock_blocks_bill(client, owner, setup):
    r = client.post("/api/invoices", headers=owner, json={"customer_id": setup["a"]["id"], "lines": [
        {"product_id": setup["zero"]["id"], "qty": "50"}]})
    assert r.status_code == 400 and "Not enough stock" in r.json()["detail"]
    # nothing half-saved
    assert D(client.get(f"/api/products/{setup['zero']['id']}", headers=owner).json()["stock_qty"]) == 5


def test_double_submit_is_ignored(client, owner, setup):
    body = {"customer_id": setup["b"]["id"], "idempotency_key": "abc-123",
            "lines": [{"product_id": setup["lam"]["id"], "qty": "1"}]}
    r1 = client.post("/api/invoices", headers=owner, json=body).json()
    r2 = client.post("/api/invoices", headers=owner, json=body).json()
    assert r1["id"] == r2["id"] and r2.get("duplicate_request")
    setup["inv_b"] = r1


# ---------------------------------------------------------------- payments
def test_partial_multiple_payments_advance_and_balance(client, owner, setup):
    a, inv = setup["a"], setup["inv1"]
    pay = lambda **kw: client.post("/api/payments", headers=owner, json={"customer_id": a["id"], **kw})
    r = pay(invoice_id=inv["id"], amount="1000", method="CASH")
    assert r.status_code == 200 and D(r.json()["customer_outstanding"]) == D("2156.50")
    # immediate identical entry is flagged as possible duplicate
    r = pay(invoice_id=inv["id"], amount="1000", method="CASH")
    assert r.status_code == 409 and r.json()["needs_confirmation"]
    r = pay(invoice_id=inv["id"], amount="1000", method="CASH", confirm_duplicate=True)
    assert r.status_code == 200
    # same UPI reference twice is a duplicate
    assert pay(invoice_id=inv["id"], amount="100", method="UPI", reference="UTR111").status_code == 200
    assert pay(invoice_id=inv["id"], amount="50", method="UPI", reference="UTR111").status_code == 409
    # cannot overpay a bill
    r = pay(invoice_id=inv["id"], amount="5000", method="BANK")
    assert r.status_code == 400 and "advance" in r.json()["detail"]
    # advance (no bill)
    assert pay(amount="500", method="BANK").status_code == 200
    acc = client.get(f"/api/customers/{a['id']}/account", headers=owner).json()
    t = acc["totals"]
    assert D(t["billed"]) == D("3156.50")
    assert D(t["paid"]) == D("2600.00")
    assert D(t["outstanding"]) == D("556.50")
    bill = [i for i in acc["invoices"] if i["id"] == inv["id"]][0]
    assert bill["payment_status"] == "PARTIAL" and D(bill["due"]) == D("1056.50")
    # other customer's balance untouched
    b_acc = client.get(f"/api/customers/{setup['b']['id']}/account", headers=owner).json()
    assert D(b_acc["totals"]["paid"]) == 0


def test_payment_must_belong_to_customer(client, owner, setup):
    r = client.post("/api/payments", headers=owner, json={"customer_id": setup["b"]["id"],
                                                          "invoice_id": setup["inv1"]["id"], "amount": "10"})
    assert r.status_code == 400


def test_refund_credit_note_and_void(client, owner, setup):
    a = setup["a"]
    # refund limited to credit available (customer owes money -> no refund without a bill)
    r = client.post("/api/payments", headers=owner, json={"customer_id": a["id"], "kind": "REFUND", "amount": "10"})
    assert r.status_code == 400
    cn = client.post("/api/credit-notes", headers=owner, json={"customer_id": a["id"], "invoice_id": setup["inv1"]["id"],
                                                              "amount": "56.50", "reason": "Rate correction"})
    assert cn.status_code == 200 and D(cn.json()["customer_outstanding"]) == D("500.00")
    pays = client.get("/api/payments", params={"customer_id": a["id"]}, headers=owner).json()["items"]
    advance = [p for p in pays if p["invoice_id"] is None][0]
    v = client.post(f"/api/payments/{advance['id']}/void", headers=owner, json={"reason": "Bounced"})
    assert D(v.json()["customer_outstanding"]) == D("1000.00")


def test_edit_payment_moves_amount(client, owner, setup):
    pays = client.get("/api/payments", params={"customer_id": setup["a"]["id"]}, headers=owner).json()["items"]
    upi = [p for p in pays if p["reference"] == "UTR111"][0]
    r = client.put(f"/api/payments/{upi['id']}", headers=owner, json={
        "invoice_id": setup["inv1"]["id"], "amount": "150", "method": "UPI", "reference": "UTR111",
        "paid_on": upi["paid_on"], "reason": "Typed wrong amount"})
    assert r.status_code == 200 and D(r.json()["customer_outstanding"]) == D("950.00")


# ---------------------------------------------------------------- factory flow
def test_factory_order_status_and_stock(client, owner, setup):
    fo = setup["inv1"]["factory_orders"][0]
    door_id = setup["door"]["id"]
    for s in ("APPROVED", "SENT_TO_FACTORY", "IN_PRODUCTION"):
        assert client.post(f"/api/factory-orders/{fo['id']}/status", headers=owner, json={"status": s}).status_code == 200
    # cannot go backwards
    assert client.post(f"/api/factory-orders/{fo['id']}/status", headers=owner, json={"status": "PENDING"}).status_code == 400
    client.post(f"/api/factory-orders/{fo['id']}/status", headers=owner, json={"status": "READY"})
    p = client.get(f"/api/products/{door_id}", headers=owner).json()
    assert D(p["stock_qty"]) == 12 and D(p["reserved_qty"]) == 2 and D(p["available_qty"]) == 10
    client.post(f"/api/factory-orders/{fo['id']}/status", headers=owner, json={"status": "DISPATCHED"})
    p = client.get(f"/api/products/{door_id}", headers=owner).json()
    assert D(p["stock_qty"]) == 10 and D(p["reserved_qty"]) == 0
    r = client.post(f"/api/factory-orders/{fo['id']}/status", headers=owner, json={"status": "DELIVERED"}).json()
    assert r["delivered_at"] and [e["to"] for e in r["events"]][-1] == "DELIVERED"
    pdf = client.get(f"/api/factory-orders/{fo['id']}/pdf", headers=owner)
    assert pdf.content[:4] == b"%PDF"


def test_cannot_cancel_bill_after_factory_dispatch(client, owner, setup):
    # clear payments first so only the factory rule blocks it
    r = client.post(f"/api/invoices/{setup['inv1']['id']}/cancel", headers=owner, json={"reason": "test"})
    assert r.status_code == 400


def test_cancel_bill_returns_stock(client, owner, setup):
    lam = setup["lam"]
    before = D(client.get(f"/api/products/{lam['id']}", headers=owner).json()["stock_qty"])
    r = client.post(f"/api/invoices/{setup['inv_b']['id']}/cancel", headers=owner, json={"reason": "Customer changed mind"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    after = D(client.get(f"/api/products/{lam['id']}", headers=owner).json()["stock_qty"])
    assert after == before + 1


def test_edit_bill_recalculates(client, owner, setup):
    b = setup["b"]
    inv = client.post("/api/invoices", headers=owner, json={"customer_id": b["id"], "lines": [
        {"product_id": setup["lam"]["id"], "qty": "2"}]}).json()
    client.post("/api/payments", headers=owner, json={"customer_id": b["id"], "invoice_id": inv["id"],
                                                      "amount": "300", "method": "CASH"})
    # reducing below paid is refused
    r = client.put(f"/api/invoices/{inv['id']}", headers=owner, json={"customer_id": b["id"], "lines": [
        {"product_id": setup["lam"]["id"], "qty": "1"}]})
    assert r.status_code == 400
    r = client.put(f"/api/invoices/{inv['id']}", headers=owner, json={"customer_id": b["id"], "lines": [
        {"product_id": setup["lam"]["id"], "qty": "4"}]})
    assert r.status_code == 200 and D(r.json()["total"]) == D("1180.00")
    acc = client.get(f"/api/customers/{b['id']}/account", headers=owner).json()
    assert D(acc["totals"]["outstanding"]) == D("880.00")


def test_mapping_change_keeps_old_bills(client, owner, setup):
    door = setup["door"]
    r = client.put(f"/api/products/{door['id']}", headers=owner, json={
        "catalogue_no": "123", "factory_order_no": "790", "name": door["name"], "sale_price": "1000",
        "purchase_cost": "700", "mapping_change_reason": "Factory renumbered"})
    assert r.status_code == 200
    inv = client.get(f"/api/invoices/{setup['inv1']['id']}", headers=owner).json()
    assert [l for l in inv["lines"] if l["catalogue_no"] == "123"][0]["factory_order_no"] == "789"
    assert client.get("/api/products/lookup", params={"catalogue_no": "123"}, headers=owner).json()["product"]["factory_order_no"] == "790"
    hist = client.get(f"/api/products/{door['id']}", headers=owner).json()["mapping_history"]
    assert hist and "789" in hist[0]["old"] and "790" in hist[0]["new"]


# ---------------------------------------------------------------- roles & isolation
def test_staff_permissions_and_customer_isolation(client, owner, setup):
    a, b = setup["a"], setup["b"]
    client.post("/api/users", headers=owner, json={"username": "clerk", "password": "clerk123", "role": "staff",
                                                   "permissions": ["billing.create", "products.view"]})
    client.post("/api/users", headers=owner, json={"username": "asha", "password": "asha123", "role": "customer",
                                                   "customer_id": a["id"]})
    clerk, asha = login(client, "clerk", "clerk123"), login(client, "asha", "asha123")
    # staff: can bill, cannot see costs, reports, payments edits, users
    p = client.get(f"/api/products/{setup['door']['id']}", headers=clerk).json()
    assert "purchase_cost" not in p and "supplier" not in p
    assert client.get("/api/dashboard", headers=clerk).status_code == 403
    assert client.get("/api/users", headers=clerk).status_code == 403
    assert client.post("/api/payments", headers=clerk, json={"customer_id": a["id"], "amount": "1"}).status_code == 403
    # staff can't change the rate without permission
    r = client.post("/api/invoices", headers=clerk, json={"customer_id": a["id"], "lines": [
        {"product_id": setup["lam"]["id"], "qty": "1", "rate": "1"}]})
    assert r.status_code == 403
    # customer: only own account, no factory numbers or costs
    me = client.get("/api/me/account", headers=asha).json()
    assert me["customer"]["id"] == a["id"]
    assert all(i["customer_id"] == a["id"] for i in me["invoices"])
    assert all("factory_order_no" not in l and "cost_total" not in l for i in me["invoices"] for l in i["lines"])
    assert all("factory_order_no" not in l for o in me["orders"] for l in o["lines"])
    for path in ("/api/customers", f"/api/customers/{b['id']}/account", "/api/invoices", "/api/products",
                 "/api/dashboard", f"/api/invoices/{setup['inv_b']['id']}"):
        assert client.get(path, headers=asha).status_code == 403, path
    assert client.get(f"/api/me/invoices/{setup['inv_b']['id']}/pdf", headers=asha).status_code == 404
    own = client.get(f"/api/me/invoices/{setup['inv1']['id']}/pdf", headers=asha)
    assert own.status_code == 200 and own.content[:4] == b"%PDF" and b"789" not in own.content
    assert client.get("/api/me/statement.pdf", headers=asha).content[:4] == b"%PDF"
    # deactivating a login kills its session immediately
    uid = [u for u in client.get("/api/users", headers=owner).json() if u["username"] == "asha"][0]["id"]
    client.patch(f"/api/users/{uid}", headers=owner, json={"is_active": False})
    assert client.get("/api/me/account", headers=asha).status_code == 401


def test_no_token_and_bad_token(client):
    assert client.get("/api/customers").status_code == 401
    assert client.get("/api/customers", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_sql_injection_is_inert(client, owner, setup):
    r = client.get("/api/customers", params={"q": "' OR 1=1; DROP TABLE customers;--"}, headers=owner)
    assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get("/api/customers", headers=owner).json()["total"] >= 2


# ---------------------------------------------------------------- import
def _xlsx(rows, head=None):
    wb = Workbook()
    ws = wb.active
    ws.append(head or ["Customer Catalogue Number", "Factory Order Number", "Product Name", "Category", "Price",
                       "Qty"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_large_import_with_errors_fix_and_commit(client, owner, setup):
    n = 20000
    rows = [[f"IMP{i}", f"FAC{i}", f"Imported Item {i}", "Laminates", 100 + i % 50, 10] for i in range(n)]
    rows.append(["IMP5", "FAC-X", "Duplicate catalogue", "Laminates", 1, 1])  # dup catalogue in file
    rows.append(["IMP-NEW", "", "Missing factory", "Laminates", 1, 1])       # missing mapping
    rows.append(["IMP-BAD", "FAC-BAD", "Bad price", "Laminates", "abc", 1])  # bad number
    rows.append(["123", "NEWF", "Existing catalogue", "Doors", 1, 1])        # exists already
    rows.append([1234.0, "FAC-FLOAT", "Excel float number", "Doors", 5, 1])  # 1234.0 -> 1234
    r = client.post("/api/imports", headers=owner, data={"mode": "create"},
                    files={"file": ("stock.xlsx", _xlsx(rows), "application/octet-stream")})
    assert r.status_code == 200, r.text
    b = r.json()
    s = b["summary"]
    assert s["total"] == n + 5 and s["errors"] == 5  # 2 dup rows + missing + bad + existing
    # commit refused while errors exist
    assert client.post(f"/api/imports/{b['id']}/commit", headers=owner, json={}).status_code == 400
    errs = {r["row"]: r for r in client.get(f"/api/imports/{b['id']}", params={"only_errors": True, "size": 50},
                                            headers=owner).json()["rows"]}
    missing = [r for r in errs.values() if r["data"]["catalogue_no"] == "IMP-NEW"][0]
    fixed = client.put(f"/api/imports/{b['id']}/rows/{missing['row']}", headers=owner,
                       json={"data": {**missing["data"], "factory_order_no": "FAC-NEW"}}).json()
    assert fixed["row"]["errors"] == [] and fixed["summary"]["errors"] == 4
    dup = [r for r in errs.values() if r["data"]["name"] == "Duplicate catalogue"][0]
    client.put(f"/api/imports/{b['id']}/rows/{dup['row']}", headers=owner, json={"data": {}, "remove": True})
    res = client.post(f"/api/imports/{b['id']}/commit", headers=owner, json={"skip_errors": True})
    assert res.status_code == 200, res.text
    assert res.json()["summary"]["created"] == n + 2
    look = client.get("/api/products/lookup", params={"catalogue_no": "IMP19999"}, headers=owner).json()
    assert look["product"]["factory_order_no"] == "FAC19999" and D(look["product"]["stock_qty"]) == 10
    assert client.get("/api/products/lookup", params={"catalogue_no": "1234"}, headers=owner).json()["product"]["factory_order_no"] == "FAC-FLOAT"
    page = client.get("/api/products", params={"q": "IMP1999", "size": 5}, headers=owner).json()
    assert page["items"][0]["catalogue_no"] == "IMP1999"  # exact match ranked first


def test_upsert_import_updates_mapping_with_history(client, owner, setup):
    data = _xlsx([["IMP7", "FAC7-NEW", "Imported Item 7", "Laminates", 999, 3]])
    b = client.post("/api/imports", headers=owner, data={"mode": "upsert"},
                    files={"file": ("u.xlsx", data, "application/octet-stream")}).json()
    assert b["summary"]["update"] == 1 and b["rows"][0]["warnings"]
    client.post(f"/api/imports/{b['id']}/commit", headers=owner, json={})
    p = client.get("/api/products/lookup", params={"catalogue_no": "IMP7"}, headers=owner).json()["product"]
    assert p["factory_order_no"] == "FAC7-NEW" and D(p["sale_price"]) == 999 and D(p["stock_qty"]) == 3
    full = client.get(f"/api/products/{p['id']}", headers=owner).json()
    assert "FAC7" in full["mapping_history"][0]["old"]


# ---------------------------------------------------------------- reports, pdfs, backups
def test_dashboard_reports_and_pdfs(client, owner, setup):
    dsh = client.get("/api/dashboard", headers=owner).json()
    assert dsh["counts"]["customers"] >= 2
    out = client.get("/api/reports/outstanding", headers=owner).json()
    assert D(dsh["outstanding_total"]) == D(out["total"])
    assert any(r["name"] == "Walnut Suede Laminate" for r in dsh["stock"]["low_stock"])
    assert client.get("/api/reports/sales", params={"group": "product"}, headers=owner).json()["rows"]
    assert client.get("/api/reports/sales", params={"group": "month", "format": "csv"}, headers=owner).status_code == 200
    pdf = client.get(f"/api/invoices/{setup['inv1']['id']}/pdf", headers=owner)
    assert pdf.content[:4] == b"%PDF"
    st = client.get(f"/api/customers/{setup['a']['id']}/statement.pdf", headers=owner)
    assert st.content[:4] == b"%PDF"
    ledger = client.get(f"/api/customers/{setup['a']['id']}/statement", headers=owner).json()
    acc = client.get(f"/api/customers/{setup['a']['id']}/account", headers=owner).json()
    assert D(ledger["closing"]) == D(acc["totals"]["outstanding"])
    assert client.get("/api/products-export", params={"fmt": "xlsx"}, headers=owner).status_code == 200


def test_backup(client, owner):
    r = client.post("/api/admin/backups", headers=owner)
    assert r.status_code == 200
    files = client.get("/api/admin/backups", headers=owner).json()["files"]
    assert files and files[0]["name"].endswith(".db")
    assert client.get("/api/admin/audit", headers=owner).json()["total"] > 10


# ---------------------------------------------------------------- shop scenario: online + bulk bills, Excel export
def test_online_and_bulk_bills_tracked_separately_and_excel(client, owner, setup):
    from openpyxl import load_workbook
    lam = setup["lam"]  # 250 per sheet, 18% GST
    c = client.post("/api/customers", headers=owner, json={"name": "Chirag Decor", "phone": "9876500099"}).json()
    online = client.post("/api/invoices", headers=owner, json={"customer_id": c["id"], "source": "ONLINE",
                                                               "lines": [{"product_id": lam["id"], "qty": "4"}]}).json()
    bulk = client.post("/api/invoices", headers=owner, json={"customer_id": c["id"], "source": "BULK",
                                                             "lines": [{"product_id": lam["id"], "qty": "2"}]}).json()
    # rate came from inventory automatically: 4 x 250 = 1000 + 18% = 1180 ; 2 x 250 = 500 + 90 = 590
    assert D(online["total"]) == D("1180.00") and online["lines"][0]["rate"] == "250.00"
    assert D(bulk["total"]) == D("590.00") and bulk["source"] == "BULK"
    # nothing paid yet
    acc = client.get(f"/api/customers/{c['id']}/account", headers=owner).json()
    assert D(acc["totals"]["outstanding"]) == D("1770.00")
    # customer pays 500 against the online bill only
    client.post("/api/payments", headers=owner, json={"customer_id": c["id"], "invoice_id": online["id"],
                                                      "amount": "500", "method": "UPI", "reference": "UTR-CH1"})
    acc = client.get(f"/api/customers/{c['id']}/account", headers=owner).json()
    by = {i["source"]: i for i in acc["invoices"]}
    assert D(by["ONLINE"]["due"]) == D("680.00") and by["ONLINE"]["payment_status"] == "PARTIAL"
    assert D(by["BULK"]["due"]) == D("590.00") and by["BULK"]["payment_status"] == "UNPAID"
    assert D(acc["totals"]["outstanding"]) == D("1270.00")
    # filter bills by type
    only_bulk = client.get("/api/invoices", headers=owner, params={"customer_id": c["id"], "source": "BULK"}).json()
    assert only_bulk["total"] == 1
    # Excel export for staff: all sheets, factory numbers included, totals right
    r = client.get(f"/api/customers/{c['id']}/export.xlsx", headers=owner)
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames[:4] == ["Summary", "Bills", "Items", "Payments"]
    summary = {row[0]: row[1] for row in wb["Summary"].iter_rows(values_only=True) if row and row[0]}
    assert summary["Balance to pay"] == 1270.0
    types = {row[0]: row for row in wb["Summary"].iter_rows(values_only=True) if row and row[0] in ("Online", "Bulk")}
    assert types["Online"][4] == 680.0 and types["Bulk"][4] == 590.0
    assert "Factory no." in [c.value for c in wb["Items"][1]]
    # customer's own Excel: no factory numbers
    client.post("/api/users", headers=owner, json={"username": "chirag", "password": "chirag1", "role": "customer",
                                                   "customer_id": c["id"]})
    me = login(client, "chirag", "chirag1")
    wb2 = load_workbook(io.BytesIO(client.get("/api/me/export.xlsx", headers=me).content))
    assert "Factory no." not in [c.value for c in wb2["Items"][1]]
    assert client.get(f"/api/customers/{c['id']}/export.xlsx", headers=me).status_code == 403


# ---------------------------------------------------------------- shop sheet format: cash vs bill, GST rounding, monthly excel
def test_shop_sheet_format_month(client, owner, setup, monkeypatch):
    from openpyxl import load_workbook
    from app.config import settings
    monkeypatch.setattr(settings, "GST_ROUND_RUPEE", True)

    def prod(code, name, brand, price):
        r = client.post("/api/products", headers=owner, json={"catalogue_no": code, "factory_order_no": "RL-" + code,
                        "name": name, "brand": brand, "hsn": "4823", "sale_price": str(price), "opening_stock": "50"})
        assert r.status_code == 200, r.text
        return r.json()

    p117 = prod("117-SM", "Suede Laminate", "Luxe", 1175)
    p3030 = prod("3030-BW", "Wood Laminate", "Wood-Maa", 960)
    pwhite = prod("WHITE-IN", "Inner White", "Inner", 450)
    assert p117["brand"] == "Luxe" and p117["hsn"] == "4823"

    def cust(name, area):
        return client.post("/api/customers", headers=owner, json={"name": name, "area": area}).json()

    kk, jb = cust("K K Hardware", "Ghatlodiya"), cust("JB Hardware", "Gota")
    assert kk["area"] == "Ghatlodiya"
    assert client.get("/api/customers", headers=owner, params={"q": "gota"}).json()["items"][0]["name"] == "JB Hardware"

    # sheet row: K K Hardware, Bill, 4 x 1175 = 4700, GST 846, Net 5546
    b1 = client.post("/api/invoices", headers=owner, json={"customer_id": kk["id"], "tax_mode": "BILL",
                     "lines": [{"product_id": p117["id"], "qty": "4"}]}).json()
    assert D(b1["tax_total"]) == D("846.00") and D(b1["total"]) == D("5546.00") and b1["tax_mode"] == "BILL"
    # sheet row: 1 x 960, GST 172.80 -> 173, Net 1133
    b2 = client.post("/api/invoices", headers=owner, json={"customer_id": kk["id"], "tax_mode": "BILL",
                     "lines": [{"product_id": p3030["id"], "qty": "1"}]}).json()
    assert D(b2["tax_total"]) == D("173.00") and D(b2["total"]) == D("1133.00")
    # sheet row: JB Hardware, Cash, 2 x 450 = 900, GST 0, Net 900
    b3 = client.post("/api/invoices", headers=owner, json={"customer_id": jb["id"], "tax_mode": "CASH",
                     "lines": [{"product_id": pwhite["id"], "qty": "2"}]}).json()
    assert D(b3["tax_total"]) == 0 and D(b3["total"]) == D("900.00") and b3["lines"][0]["tax_rate"] == "0.00"
    # K K pays first bill fully
    client.post("/api/payments", headers=owner, json={"customer_id": kk["id"], "invoice_id": b1["id"],
                                                      "amount": "5546", "method": "BANK", "reference": "NEFT-KK1"})
    # cash-only filter
    cash = client.get("/api/invoices", headers=owner, params={"tax_mode": "CASH", "customer_id": jb["id"]}).json()
    assert cash["total"] == 1

    client.put("/api/settings/shop", headers=owner, json={"monthly_target": "250000"})
    rep = client.get("/api/reports/monthly", headers=owner).json()
    s = rep["summary"]
    assert D(s["sales_target"]) == D("250000.00")
    areas = {a["area"]: a for a in rep["areas"]}
    assert D(areas["Ghatlodiya"]["net"]) == D("6679.00") and D(areas["Ghatlodiya"]["pending"]) == D("1133.00")
    assert D(areas["Gota"]["net"]) == D("900.00") and D(areas["Gota"]["gst"]) == 0
    mine = [r for r in rep["rows"] if r["customer"] in ("K K Hardware", "JB Hardware")]
    assert {(r["design"], r["category"], r["brand"], r["payment"]) for r in mine} == {
        ("117-SM", "Bill", "Luxe", "Paid"), ("3030-BW", "Bill", "Wood-Maa", "Pending"), ("WHITE-IN", "Cash", "Inner", "Pending")}

    x = client.get("/api/reports/monthly.xlsx", headers=owner)
    assert x.status_code == 200
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Monthly Sales Tracker", "Monthly Summary", "Area Wise"]
    head = [c.value for c in wb["Monthly Sales Tracker"][1]]
    assert head[:8] == ["Date", "Dealer / Customer", "Area", "Contact No.", "Category", "Brand", "Design / Code", "Product"]
    summ = {r[0]: r[1] for r in wb["Monthly Summary"].iter_rows(values_only=True) if r[0]}
    assert summ["Sales Target"] == 250000.0 and "Pending Payments" in summ

    # bill PDF in shop format: design code shown, factory number hidden, amount in words
    pdf = client.get(f"/api/invoices/{b2['id']}/pdf", headers=owner)
    assert pdf.content[:4] == b"%PDF"
    cpdf = client.get(f"/api/invoices/{b3['id']}/pdf", headers=owner)
    assert cpdf.content[:4] == b"%PDF"


def test_amount_in_words():
    from app.pdf import amount_in_words
    assert amount_in_words("1133") == "One Thousand One Hundred Thirty Three Rupees Only"
    assert amount_in_words("250000") == "Two Lakh Fifty Thousand Rupees Only"
    assert amount_in_words("5546.50") == "Five Thousand Five Hundred Forty Six Rupees and Fifty Paise Only"


def test_simple_dashboard(client, owner, setup):
    d = client.get("/api/dashboard/simple", headers=owner, params={"period": "all"}).json()
    for k in ("orders", "orders_pending", "orders_delivered", "payment_received", "payment_pending", "to_deliver", "to_collect", "recent"):
        assert k in d
    assert d["orders"] == d["orders_pending"] + d["orders_delivered"]
    inv = d["to_deliver"][0]
    client.post(f"/api/invoices/{inv['id']}/delivery", headers=owner, json={"delivered": True})
    d2 = client.get("/api/dashboard/simple", headers=owner, params={"period": "all"}).json()
    assert d2["orders_pending"] == d["orders_pending"] - 1
    out = client.get("/api/reports/outstanding", headers=owner).json()
    assert D(d2["customers_owe_total"]) == D(out["total"])
    assert client.get("/api/dashboard/simple", headers=owner, params={"period": "today"}).status_code == 200
