# Brightloop Subscription Management System

One system to run plans, subscriptions and recurring billing for Brightloop Software
(Odoo x Make-A-Thon challenge). FastAPI + SQLAlchemy + SQLite backend, Tailwind single-page frontend.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install fastapi "uvicorn[standard]" sqlalchemy pydantic email-validator python-dateutil pyjwt jinja2 httpx pytest
.venv/bin/python run.py          # http://127.0.0.1:8000  (API docs at /docs)
```

With uv: `uv run run.py` and `uv run pytest`.

On first start the database (`brightloop.db`) is created and seeded with demo data. Delete the file to start over;
set `SEED_DEMO_DATA=0` for an empty system with only the admin account.

| Role | Email | Password |
|---|---|---|
| Admin | admin@brightloop.com | BrightloopAdmin#2026 |
| Staff | staff@brightloop.com | BrightloopStaff#2026 |
| Customer (enterprise) | acme@corp.com | CustomerPass#2026 |
| Customer (small shop) | retail@shop.com | CustomerPass#2026 |

The login page has one-click buttons for each.

## Tests

```bash
.venv/bin/python -m pytest -q
```

56 tests cover the four phases, including a load test that inserts 5,000 subscriptions, 20,000 invoices and
15,000 payments and checks every finance page answers in under 2 seconds.

## How each scene is handled

| Scene | What the system does |
|---|---|
| Sign-up & access | Unique email; password must be more than 8 characters with upper, lower and special characters; PBKDF2-SHA256 hashing; JWT sessions. Forgot-password emails a one-hour, single-use link. Admin / staff / customer roles; only the admin adds staff. |
| Launching a plan | Products with type, sales and cost price, notes and variants (Brand: Odoo Brand Edition adds 560). Plans with daily/weekly/monthly/yearly billing, minimum quantity, availability dates and per-plan rules: auto-close at expiry, close early, pause, renew. |
| Quote → subscription | Quotation templates (plan + lines + validity days + contract length) create a pre-filled quote in one click. Numbers `SUB-00001…`. Draft → Quotation → Confirmed → Active → Closed (plus Paused), every change recorded in a history timeline. Customers can accept or decline quotes themselves. |
| Billing day | "Run billing" invoices every due subscription (`INV-00001…`) with customer, lines, taxes and totals filled in. Idempotent: one invoice per subscription per period, enforced by a unique constraint, so running it twice never double-bills; missed periods are caught up so nothing is skipped. Month-end dates do not drift (31 Jan → 28 Feb → 31 Mar). Billing stops at expiry and subscriptions auto-close when their plan says so. Invoices: Draft → Confirmed → Paid (or Cancelled), send by email, print / save as PDF. |
| Better price | Admin-only discount rules: percentage or fixed, minimum purchase or quantity, date window, max uses, for a product or whole subscriptions (optionally one specific subscription). The best eligible rule is applied to the next invoice automatically and stops once expired or used up; tax is computed on the discounted amount. |
| Money comes in | Payments with method, amount, date and note against an invoice; partial payments reduce the balance, the invoice flips to Paid at zero. Overpayments are refused. Customers can pay their own invoices in the portal (simulated checkout). Overdue chase list sorted by age with contact details. |
| Finance lead | Dashboard: active subscriptions, MRR, ARR, collected, outstanding, overdue, 12-month invoiced-vs-collected trend, status and plan breakdowns, filters by date range, plan and customer. |

## Project layout

```
backend/app/
  main.py            app, routers, startup (create tables, bootstrap admin, seed demo)
  models.py          all tables
  schemas.py         request/response validation
  auth.py            password policy, hashing, JWT, role guards
  services/          subscription lifecycle, billing engine, discounts, taxes, payments, analytics
  routers/           REST endpoints
  seed_data.py       admin bootstrap + demo dataset
backend/tests/       pytest suites per phase
frontend/templates/  index.html (SPA shell), invoice_print.html
frontend/static/     app.js, styles.css
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///brightloop.db` | Database location |
| `SECRET_KEY` | generated into `.secret_key` | JWT signing key |
| `APP_BASE_URL` | `http://127.0.0.1:8000` | Used in reset-password links |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | unset | Real email delivery. Without them emails are logged and shown to the admin under **Email outbox**. |
| `SEED_DEMO_DATA` | `1` | Seed demo data into an empty database |
