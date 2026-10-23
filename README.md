# Luxe Laminate Management System

One application for the whole business: products with their two numbers (customer catalogue number and factory order number), bills, payments, customer accounts, factory orders, stock, purchases, expenses, reports and backups.

Typing a customer catalogue number (for example `123`) finds exactly one product and shows its factory order number (`789`). Bills keep `123`. Factory orders use `789`. If a number is missing, duplicated or exists in two catalogue books, the system shows a warning instead of guessing.

---

## 1. Install and start (Windows)

1. Install **Python 3.11 or newer** from <https://www.python.org/downloads/>. On the first installer screen, tick **"Add python.exe to PATH"**.
2. Unzip this folder somewhere permanent, for example `C:\LuxeLaminate`.
3. Double-click **`run.bat`**.
   The first start installs everything (a few minutes), creates `.env` with a fresh secret key, and builds the database.
4. Open <http://localhost:8000> in Chrome or Edge.

### Create the owner login (once)

Open PowerShell in the folder and run:

```powershell
.venv\Scripts\python -m scripts.create_owner owner YourStrongPassword "Your Name"
```

The same command resets the owner password if it is ever forgotten.

### Optional: demo data to try things out

```powershell
.venv\Scripts\python -m scripts.seed
```

This adds 300 products, 10 customers and 25 bills, plus three logins: `owner / owner123`, `staff / staff123`, `sharma / cust123` (a customer login). **Use demo data only on a test copy, never on the real shop database.**

To test speed with a large inventory:

```powershell
.venv\Scripts\python -m scripts.seed --products 100000
```

### Shop details on bills

Edit `.env` (open it with Notepad) and set `BUSINESS_NAME`, `BUSINESS_ADDRESS`, `BUSINESS_PHONE` and `BUSINESS_GSTIN`. Restart `run.bat` after saving.

### Using it from phones and other computers in the shop

`run.bat` listens on the local network. Find the PC's IP address (`ipconfig` in PowerShell, look for "IPv4 Address", for example `192.168.1.20`) and open `http://192.168.1.20:8000` on the other device. Windows Firewall may ask once to allow Python; choose **Private networks**.

---

## 2. Daily workflow for staff

1. **New bill** → search the customer by name, phone, customer ID or a bill number (or add a new customer).
2. Type the **catalogue number** from the customer's book and press Enter.
3. The product appears with its **factory number** in the two-part tag. Check the name and price.
4. Enter the quantity. Choose **From stock** or **Order from factory** (add dimensions, finish and instructions for the factory).
5. Add more items, enter any payment received now, and press **Save bill**.
6. Print the bill or the customer statement from the confirmation screen.

"Order from factory" lines create a factory order automatically. Move it through the statuses from **Factory orders**:

| Status | What happens to stock |
| --- | --- |
| Pending → Approved → Sent to factory → In production | Nothing yet |
| Ready | Goods are added to stock and reserved for that customer |
| Dispatched | Reserved goods leave stock |
| Delivered | Order closed |
| Cancelled | Allowed until dispatch; received goods stay in stock as free stock |

### "How much do I owe?"

Open **Customers** → the customer → the totals show billed, paid, refunds, credit notes and the outstanding balance. Press **Statement PDF** for a printable ledger with running balance and unpaid bills.

---

## 3. Importing the existing inventory

**Import from Excel** → **Download template** shows the expected columns.

- Required: `catalogue_no`, `factory_order_no`, `name`.
- Optional: `catalogue` (book name, default MAIN), `category`, `description`, `size`, `finish`, `unit`, `sale_price`, `purchase_cost`, `tax_rate` (default 18), `quantity`, `reorder_level`, `supplier`.
- Common headings such as "Customer Catalogue Number", "Factory Order Number", "Product Name", "Price", "Qty" are recognised automatically.

The preview checks every row before anything is saved:

- missing catalogue or factory number, missing name;
- the same catalogue number twice in the file, or the same factory number twice;
- a catalogue number that already exists (in "Add new only" mode);
- a factory number already used by a different product;
- prices or quantities that are not numbers.

Fix a row on screen and press **Save fix**, remove it, or import only the valid rows. Choose **"Add new and update existing"** to bulk-update prices, stock or mappings. Every mapping change is kept in the product's history, and old bills and orders keep the numbers they were made with.

**Excel tip:** if catalogue numbers have leading zeros (`0123`), format that column as **Text** in Excel before saving. Otherwise Excel turns `0123` into `123`, and in this system they are different numbers.

---

## 4. Roles and permissions

- **Owner** sees and does everything, including costs, suppliers, profit, logins, backups and the activity log.
- **Staff** see only what the owner ticks in **Logins & permissions** (billing, payments, factory orders, stock, import, reports, purchase costs, and so on). Without "See purchase costs", staff never see costs, suppliers or profit.
- **Customer** logins see only their own bills, payments, balance and order status. They never see factory numbers, costs or other customers. Create one from the customer's page with **Create customer login**.

All rules are enforced on the server, not only hidden in the screens.

---

## 5. Backups (important)

### Automatic daily backup on Windows

1. Open **Task Scheduler** → **Create Basic Task** → name it "Luxe backup" → **Daily**, for example 9:00 PM.
2. Action: **Start a program**
   - Program: `C:\LuxeLaminate\.venv\Scripts\python.exe`
   - Arguments: `-m scripts.backup`
   - Start in: `C:\LuxeLaminate`
3. Finish.

The last 30 automatic backups are kept in the `backups` folder (change `BACKUP_KEEP` in `.env`). **Copy that folder to a pen drive or cloud drive (Google Drive, OneDrive) regularly.** A backup on the same PC does not protect against a dead hard disk.

The owner can also press **Back up now** and **Download** in **Settings & backup**.

### Restore

1. Close the `run.bat` window (stop the server).
2. Run:

   ```powershell
   .venv\Scripts\python -m scripts.restore backups\luxe_20261012_210000_auto.db
   ```

3. Type `YES`. A safety copy of the current data is saved first.
4. Start `run.bat` again.

---

## 6. PostgreSQL (for larger setups or multiple branches)

SQLite is enough for one shop with several staff and hundreds of thousands of products. For heavy multi-branch use:

1. Install PostgreSQL and create a database and user named `luxe`.
2. In `.env` set `DATABASE_URL=postgresql+psycopg2://luxe:PASSWORD@localhost:5432/luxe`.
3. Run `.venv\Scripts\alembic upgrade head`, then create the owner as above.
4. Backups use `pg_dump`, which must be on PATH.

The automated tests run on SQLite. Test the PostgreSQL setup with your own data before switching the shop over.

---

## 7. Putting it on the internet (so customers can log in from home)

Run it on a small cloud server (Ubuntu) behind HTTPS:

```bash
sudo apt install python3-venv nginx certbot python3-certbot-nginx
git clone <your copy> /opt/luxe && cd /opt/luxe && ./run.sh   # first run sets up everything
```

Then:

- create a `systemd` service that runs `/opt/luxe/run.sh` so it restarts automatically;
- point nginx at `http://127.0.0.1:8000`;
- run `sudo certbot --nginx -d yourdomain.com` for HTTPS.

**Never expose it to the internet without HTTPS.** Set a long `SECRET_KEY` (run.bat and run.sh create one automatically). Schedule `python -m scripts.backup` with cron and copy backups off the server.

---

## 8. For developers

| Path | What it is |
| --- | --- |
| `app/models.py` | Database tables |
| `app/services.py` | All business rules: mapping lookup, stock, billing, balances, factory status flow |
| `app/importer.py` | Excel/CSV import and validation |
| `app/routers/` | API endpoints (`/docs` shows them interactively) |
| `app/pdf.py` | Invoice, statement and factory order PDFs |
| `static/` | Browser interface (plain JavaScript, no build step) |
| `migrations/` | Alembic schema migrations |
| `tests/` | Automated tests |

### Design rules

- **Exact money:** amounts are stored as whole paise, quantities as thousandths and percentages as basis points. There are no floating-point rounding errors.
- **Balances are never stored.** They are always calculated from bills, payments, refunds and credit notes, so they cannot drift out of sync.
- **Snapshots:** bill lines and factory order lines copy the product name, both numbers and the rate at the time of sale.
- **One transaction per action:** each bill, payment, import or status change either fully saves or saves nothing.
- **Duplicate protection:** double-clicking Save cannot create two bills or two payments. A payment matching a recent one, or reusing a UPI/cheque reference, needs confirmation.
- **Audit:** every important change is recorded with who did it and when (Settings & backup → Activity log).

### Run the tests

```bash
pip install -r requirements.txt
python -m pytest -q
```

### Change the database schema

Edit `app/models.py`, then:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

### Known limits

- GST is shown as one total per line. A CGST/SGST/IGST split by customer state is not implemented.
- Online payments are recorded manually (method ONLINE, with reference). No payment gateway is connected.
- "Online" bills are a bill type; there is no public online shop.
- The interface uses the Atkinson Hyperlegible font from Google Fonts and falls back to the system font when offline.
