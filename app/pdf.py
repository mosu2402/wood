import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import settings

INK = colors.HexColor("#1F2A2E")
WALNUT = colors.HexColor("#5A3A22")
LINE = colors.HexColor("#C9CEC6")
SHADE = colors.HexColor("#ECEFEA")

_styles = getSampleStyleSheet()
S = {
    "h": ParagraphStyle("h", parent=_styles["Title"], fontName="Helvetica-Bold", fontSize=18, textColor=WALNUT,
                        alignment=0, spaceAfter=2),
    "b": ParagraphStyle("b", parent=_styles["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=INK),
    "bb": ParagraphStyle("bb", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=INK),
    "small": ParagraphStyle("s", parent=_styles["Normal"], fontName="Helvetica", fontSize=8, leading=10,
                            textColor=colors.HexColor("#55605F")),
    "doc": ParagraphStyle("doc", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=13, leading=17, spaceAfter=3, textColor=INK,
                          alignment=2),
}


def rs(v) -> str:
    v = float(v)
    s = f"{abs(v):,.2f}"
    return ("-" if v < 0 else "") + "Rs. " + s


def _header(title: str, right_lines: list[str]):
    left = [Paragraph(settings.BUSINESS_NAME, S["h"])]
    for line in (settings.BUSINESS_ADDRESS, settings.BUSINESS_PHONE,
                 f"GSTIN: {settings.BUSINESS_GSTIN}" if settings.BUSINESS_GSTIN else ""):
        if line:
            left.append(Paragraph(line, S["b"]))
    right = [Paragraph(title, S["doc"])] + [Paragraph(x, ParagraphStyle("r", parent=S["b"], alignment=2))
                                             for x in right_lines]
    t = Table([[left, right]], colWidths=[110 * mm, 70 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, WALNUT),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _grid(data, widths, num_cols=(), bold_last=False):
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5), ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
             ("BACKGROUND", (0, 0), (-1, 0), SHADE), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
             ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    for c in num_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if bold_last:
        style.append(("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9))
    t.setStyle(TableStyle(style))
    return t


def _build(story) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=settings.BUSINESS_NAME)

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#55605F"))
        canvas.drawString(15 * mm, 8 * mm, f"{settings.BUSINESS_NAME} - computer generated document")
        canvas.drawRightString(195 * mm, 8 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _party(c: dict) -> list:
    out = [Paragraph("Bill to", S["small"]), Paragraph(f"{c['name']} ({c['code']})", S["bb"])]
    for x in (c.get("address"), c.get("phone"), f"GSTIN: {c['gstin']}" if c.get("gstin") else ""):
        if x:
            out.append(Paragraph(x, S["b"]))
    return out


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _three(n: int) -> str:
    h, r = divmod(n, 100)
    return " ".join(x for x in ((_ONES[h] + " Hundred") if h else "", _two(r) if r else "") if x)


def amount_in_words(v) -> str:
    """Indian numbering: 1,23,45,678.50 -> One Crore Twenty Three Lakh ... Rupees and Fifty Paise Only."""
    from decimal import ROUND_HALF_UP, Decimal
    v = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees, paise = int(v), int((v - int(v)) * 100)
    if rupees == 0 and paise == 0:
        return "Zero Rupees Only"
    parts, n = [], rupees
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(_three(crore) + " Crore" if crore < 1000 else amount_in_words(crore).replace(" Rupees Only", "") + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    text = (" ".join(parts) + " Rupees") if rupees else ""
    if paise:
        text = (text + " and " if text else "") + _two(paise) + " Paise"
    return text.strip() + " Only"


def invoice_pdf(inv: dict, customer: dict, payments: list[dict]) -> bytes:
    """Customer bill in the shop's usual layout. Shows the design/catalogue number, never the factory number."""
    gst = inv.get("tax_mode", "BILL") == "BILL"
    cancelled = inv["status"] == "CANCELLED"
    label = {"MANUAL": "SHOP", "ONLINE": "ONLINE", "DELIVERY": "DELIVERY", "BULK": "BULK"}.get(inv.get("source"), "")
    W = 180 * mm
    box = [("BOX", (0, 0), (-1, -1), 0.8, INK), ("TEXTCOLOR", (0, 0), (-1, -1), INK)]
    story = []

    # firm name band
    head = [[Paragraph(f"<b>{settings.BUSINESS_NAME.upper()}</b>",
                       ParagraphStyle("firm", parent=S["b"], fontSize=18, leading=22, alignment=1, textColor=WALNUT))]]
    sub = " | ".join(x for x in (settings.BUSINESS_ADDRESS, settings.BUSINESS_PHONE,
                                 f"GSTIN: {settings.BUSINESS_GSTIN}" if settings.BUSINESS_GSTIN else "") if x)
    if sub:
        head.append([Paragraph(sub, ParagraphStyle("sub", parent=S["b"], alignment=1))])
    t = Table(head, colWidths=[W])
    t.setStyle(TableStyle(box + [("BACKGROUND", (0, 0), (-1, 0), SHADE), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(t)

    # memo type row
    title = ("TAX INVOICE" if gst else "DEBIT MEMO (CASH)") + (" - CANCELLED" if cancelled else "")
    t = Table([[Paragraph(f"<b>{title}</b>", S["b"]), Paragraph(f"<b>{label}</b>", ParagraphStyle("c", parent=S["b"], alignment=1)),
                Paragraph("<b>Original</b>", ParagraphStyle("r", parent=S["b"], alignment=2))]], colWidths=[W / 3] * 3)
    t.setStyle(TableStyle(box))
    story.append(t)

    # party + invoice no
    party = [Paragraph(f"M/s. : <b>{customer['name'].upper()}</b>", ParagraphStyle("p", parent=S["b"], fontSize=11, leading=14))]
    for x in (customer.get("address"), customer.get("area"), f"Mobile: {customer['phone']}" if customer.get("phone") else "",
              f"GSTIN: {customer['gstin']}" if customer.get("gstin") else "", f"Customer ID: {customer['code']}"):
        if x:
            party.append(Paragraph(x, S["b"]))
    d = inv["invoice_date"]
    date_txt = f"{d[8:10]}/{d[5:7]}/{d[0:4]}"
    meta = Table([[Paragraph("<b>Invoice No.</b>", S["b"]), Paragraph(f": <b>{inv['number']}</b>", S["b"])],
                  [Paragraph("<b>Date</b>", S["b"]), Paragraph(f": <b>{date_txt}</b>", S["b"])]], colWidths=[22 * mm, 38 * mm])
    meta.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SHADE), ("TEXTCOLOR", (0, 0), (-1, -1), INK)]))
    t = Table([[party, meta]], colWidths=[115 * mm, 65 * mm])
    t.setStyle(TableStyle(box + [("LINEBEFORE", (1, 0), (1, 0), 0.8, INK), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    story.append(t)

    # items
    hdr = ["SrNo", "Product Name", "HSN", "Qty", "Unit", "Rate", "Amount"]
    rows = [hdr]
    for i, ln in enumerate(inv["lines"], 1):
        name = f"<b>{ln['catalogue_no']}</b>"
        if ln.get("brand"):
            name += f" {ln['brand']}"
        name += f" - {ln['product_name']}"
        extra = " / ".join(x for x in (ln.get("dimensions"), ln.get("finish")) if x)
        if extra:
            name += f"<br/><font size=7>{extra}</font>"
        if float(ln["discount_pct"] or 0):
            name += f"<br/><font size=7>Discount {float(ln['discount_pct']):g}%</font>"
        rows.append([str(i), Paragraph(name, S["b"]), ln.get("hsn") or "", f"{float(ln['qty']):.3f}", ln["unit"].title(),
                     f"{float(ln['rate']):,.2f}", f"{float(ln['taxable']):,.2f}"])
    min_rows = 12
    while len(rows) < min_rows + 1:
        rows.append([""] * 7)
    widths = [12 * mm, 74 * mm, 16 * mm, 18 * mm, 14 * mm, 20 * mm, 26 * mm]
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle(box + [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9), ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK), ("ALIGN", (3, 0), (3, -1), "RIGHT"), ("ALIGN", (5, 0), (6, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 1), (-1, -1), 2), ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
    ] + [("LINEAFTER", (c, 0), (c, -1), 0.5, INK) for c in range(6)]))
    story.append(t)

    # words + totals
    left = [Paragraph(f"<b>Rs. (in words) :</b> {amount_in_words(inv['total'])}", S["b"]), Spacer(1, 6)]
    if customer.get("gstin") or settings.BUSINESS_GSTIN:
        left.append(Paragraph(f"<b>Our GSTIN:</b> {settings.BUSINESS_GSTIN or '-'} &nbsp;&nbsp; "
                              f"<b>Party GSTIN:</b> {customer.get('gstin') or '-'}", S["b"]))
    if settings.BANK_DETAILS:
        left.append(Paragraph(f"<b>Bank / UPI:</b> {settings.BANK_DETAILS}", S["b"]))
    if inv.get("notes"):
        left += [Spacer(1, 4), Paragraph(f"<b>Note :</b> {inv['notes']}", S["b"])]
    tot = [["Sub Total", f"{float(inv['subtotal']):,.2f}"]]
    if float(inv["discount_total"]):
        tot.append(["Discount", f"- {float(inv['discount_total']):,.2f}"])
    if gst:
        half = float(inv["tax_total"]) / 2
        tot += [["Taxable Value", f"{float(inv['taxable_total']):,.2f}"], ["CGST", f"{half:,.2f}"], ["SGST", f"{half:,.2f}"]]
    tot += [["Grand Total", f"{float(inv['total']):,.2f}"], ["Paid", f"{float(inv['settled']):,.2f}"],
            ["Balance Due", f"{float(inv['due']):,.2f}"]]
    gi = len(tot) - 3
    tt = Table(tot, colWidths=[28 * mm, 32 * mm])
    tt.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("TEXTCOLOR", (0, 0), (-1, -1), INK), ("BACKGROUND", (0, gi), (-1, gi), SHADE),
                            ("FONT", (0, gi), (-1, gi), "Helvetica-Bold", 10), ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10),
                            ("LINEABOVE", (0, gi), (-1, gi), 0.8, INK)]))
    t = Table([[left, tt]], colWidths=[114 * mm, 66 * mm])
    t.setStyle(TableStyle(box + [("LINEBEFORE", (1, 0), (1, 0), 0.8, INK), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t)

    # payments received against this bill
    live = [p for p in payments if not p["is_void"]]
    if live:
        txt = "; ".join(f"{p['paid_on'][8:10]}/{p['paid_on'][5:7]} {p['method']} "
                        f"{'-' if p['kind'] == 'REFUND' else ''}Rs. {float(p['amount']):,.2f}" for p in live)
        t = Table([[Paragraph(f"<b>Payments received:</b> {txt}", S["b"])]], colWidths=[W])
        t.setStyle(TableStyle(box))
        story.append(t)

    # terms + signature
    terms = [Paragraph("<b>Terms &amp; Condition :</b>", S["b"])]
    for i, line in enumerate([x for x in settings.BILL_TERMS.split("|") if x.strip()], 1):
        terms.append(Paragraph(f"<i>{i}. {line.strip()}</i>", S["small"]))
    sign = [Paragraph(f"For, {settings.BUSINESS_NAME}", ParagraphStyle("f", parent=S["b"], alignment=2)), Spacer(1, 24),
            Paragraph("<i>(Authorized Signatory)</i>", ParagraphStyle("a", parent=S["small"], alignment=2))]
    t = Table([[terms, sign]], colWidths=[120 * mm, 60 * mm])
    t.setStyle(TableStyle(box + [("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(t)
    return _build(story)


def statement_pdf(customer: dict, totals: dict, ledger: dict, invoices: list[dict], since, upto) -> bytes:
    period = f"{since or 'Beginning'} to {upto or 'Today'}"
    story = [_header("ACCOUNT STATEMENT", [period]), Spacer(1, 6)]
    story += _party(customer)
    story.append(Spacer(1, 8))
    summary = [["Total billed", "Payments received", "Refunds", "Credit notes", "Outstanding balance"],
               [rs(totals["billed"]), rs(totals["paid"]), rs(totals["refunded"]), rs(totals["credited"]),
                rs(totals["outstanding"])]]
    story.append(_grid(summary, [36 * mm] * 5, num_cols=(0, 1, 2, 3, 4), bold_last=True))
    story += [Spacer(1, 10), Paragraph("Ledger", S["bb"]), Spacer(1, 3)]
    rows = [["Date", "Particulars", "Debit", "Credit", "Balance"], ["", "Opening balance", "", "", f"{float(ledger['opening']):,.2f}"]]
    for r in ledger["rows"]:
        rows.append([r["date"], Paragraph(r["particulars"], S["b"]),
                     f"{float(r['debit']):,.2f}" if float(r["debit"]) else "",
                     f"{float(r['credit']):,.2f}" if float(r["credit"]) else "", f"{float(r['balance']):,.2f}"])
    rows.append(["", "Closing balance", "", "", f"{float(ledger['closing']):,.2f}"])
    story.append(_grid(rows, [22 * mm, 82 * mm, 25 * mm, 25 * mm, 26 * mm], num_cols=(2, 3, 4), bold_last=True))
    open_inv = [i for i in invoices if i["status"] == "ISSUED" and float(i["due"]) > 0]
    if open_inv:
        story += [Spacer(1, 10), Paragraph("Unpaid bills", S["bb"]), Spacer(1, 3)]
        rows = [["Bill", "Date", "Total", "Paid", "Due"]]
        for i in open_inv:
            rows.append([i["number"], i["invoice_date"], f"{float(i['total']):,.2f}", f"{float(i['settled']):,.2f}",
                         f"{float(i['due']):,.2f}"])
        story.append(_grid(rows, [40 * mm, 30 * mm, 36 * mm, 36 * mm, 38 * mm], num_cols=(2, 3, 4)))
    return _build(story)


def factory_order_pdf(fo: dict) -> bytes:
    """Sent to the factory: factory number is the main reference, catalogue number for cross-checking."""
    story = [_header("FACTORY ORDER", [f"No. {fo['number']}", f"Date {fo['created_at'][:10]}",
                                       f"Status {fo['status'].replace('_', ' ').title()}"]), Spacer(1, 6),
             Paragraph("To", S["small"]), Paragraph(fo.get("supplier") or "", S["bb"]), Spacer(1, 4)]
    if fo.get("expected_date"):
        story.append(Paragraph(f"Required by: {fo['expected_date']}", S["b"]))
    story.append(Spacer(1, 8))
    rows = [["#", "Factory No.", "Product", "Qty", "Dimensions", "Finish", "Instructions", "Our ref."]]
    for i, ln in enumerate(fo["lines"], 1):
        rows.append([str(i), Paragraph(f"<b>{ln['factory_order_no']}</b>", S["b"]), Paragraph(ln["product_name"], S["b"]),
                     f"{ln['qty']} {ln['unit']}", Paragraph(ln["dimensions"] or "-", S["b"]),
                     Paragraph(ln["finish"] or "-", S["b"]), Paragraph(ln["instructions"] or "-", S["b"]),
                     f"Cat {ln['catalogue_no']}"])
    story.append(_grid(rows, [7 * mm, 24 * mm, 38 * mm, 16 * mm, 24 * mm, 20 * mm, 34 * mm, 17 * mm], num_cols=(3,)))
    if fo.get("notes"):
        story += [Spacer(1, 8), Paragraph("Notes: " + fo["notes"], S["b"])]
    return _build(story)
