# Brightloop - Subscription Management System

Our project for the **Odoo x Make-A-Thon**. The brief: Brightloop Software sells everything on
subscription but runs on spreadsheets, hand-typed invoices and bank statements. Build one system that
handles products, plans, subscriptions, recurring billing, payments and reporting.

We built all of that, then added a few things we thought a real subscription business would want:
a revenue forecast, a recommendations engine, a tamper-proof billing record for every subscription,
and a proper customer portal (timeline, price-change alerts, price lock and a QR pass).

**Stack:** FastAPI + SQLAlchemy + SQLite on the backend, plain JavaScript + Tailwind on the frontend
(no build step). 85 automated tests.

---

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install fastapi "uvicorn[standard]" sqlalchemy pydantic email-validator python-dateutil pyjwt jinja2 qrcode httpx pytest
.venv/bin/python run.py
```

Or with uv: `uv run run.py`.

Open http://127.0.0.1:8000 (API docs at http://127.0.0.1:8000/docs).

The first run creates `brightloop.db` and fills it with sample data. Delete that file to start over,
or set `SEED_DEMO_DATA=0` for an empty system with just the admin account.

### Logins

The login page has one-click buttons for these.

| Role | Email | Password |
|---|---|---|
| Admin | admin@brightloop.com | BrightloopAdmin#2026 |
| Staff | staff@brightloop.com | BrightloopStaff#2026 |
| Customer (enterprise) | acme@corp.com | CustomerPass#2026 |
| Customer (small shop) | retail@shop.com | CustomerPass#2026 |

### Tests

```bash
.venv/bin/python -m pytest -q
```

---

## Demo in 5 minutes

1. Open the site: press any key on the intro screen to get to the login page.
2. Sign in as **Admin**. Go to **AI revenue forecast** and click **Load simulation data**; this plays
   out 18 months of customers (sign-ups, churn, renewals, upsells, billing, payments) so every page
   has realistic numbers.
3. **Dashboard**: MRR, ARR, collections, overdue chase list, top recommendations.
4. **Invoices → Run billing**: invoices everything that's due. Run it again; nothing is duplicated.
5. **Recommendations → Run autopilot**: runs billing, confirms drafts and emails overdue reminders,
   all logged.
6. Open any subscription: the **Black box** card shows its verified event chain. Click **Flight
   recorder report**.
7. **Products → Price change** on CRM Pro: schedule a price rise; affected customers are notified.
8. Sign out and sign in as **Customer · Retail shop**: check **Price guardian** (lock the price),
   **Timeline** and **QR passes** (open the check page).

---

## The brief, scene by scene

**A new customer signs up.** Email + password sign-up (one account per email; password must be more
than 8 characters with upper, lower and special characters). Forgot-password emails a link that works
once and expires after an hour. Three roles: admin (everything), staff (day-to-day, can't touch the
catalog, plans, taxes or discounts), customer (only their own data, through the portal). Only the
admin can add staff.

**Launching a new plan.** Products with type, sales price, cost price, notes and variants. A variant
adds to the price, e.g. the Odoo Brand Edition adds 560. Plans have a price, billing frequency
(daily / weekly / monthly / yearly), minimum quantity, availability dates, and per-plan switches for
auto-close at expiry, close early, pause (with an optional maximum length) and renew.

**Turning a quote into a subscription.** Quotation templates hold a plan, product lines and how many
days the quote stays valid; one click turns a template into a quote for a customer. Subscriptions are
numbered SUB-00001 onwards and move Draft → Quotation → Confirmed → Active → Closed (or Paused), shown
as a pipeline on each subscription. Customers can accept or decline quotes themselves.

**Billing day.** "Run billing" invoices every subscription that's due, with customer, lines, taxes
and totals filled in. It's safe to run any number of times: there's a unique constraint on
subscription + billing period, so nothing is billed twice, and missed periods are caught up so
nothing is skipped. Monthly dates don't drift (31 Jan → 28 Feb → 31 Mar). Invoices go Draft →
Confirmed → Paid (or Cancelled) and can be emailed or printed / saved as PDF.

**A customer asks for a better price.** Only the admin creates discount rules: percentage or fixed,
minimum purchase or quantity, start and end dates, maximum uses, for a product or whole subscriptions
(or one specific subscription). The best matching discount is applied to the next invoice
automatically and stops when it expires or runs out. Tax is worked out on the discounted amount.

**The money comes in.** Payments with method, amount, date and note against an invoice. Part
payments reduce the balance; the invoice flips to Paid at zero. Overpayments are refused. Customers
can pay their own invoices from the portal (simulated checkout, no real gateway).

**The finance lead at month end.** A dashboard with active subscriptions, MRR, ARR, collected,
outstanding and overdue amounts, a 12-month invoiced-vs-collected chart, breakdowns by status, plan
and payment method, and an overdue chase list with contact details. Filters by date, plan and
customer. `test_phase4.py` loads 5,000 subscriptions and ~20,000 invoices and checks every finance
page answers in under 2 seconds.

---

## Extras

**AI revenue forecast.** A Monte Carlo simulation fitted to the company's own history. It rebuilds
month-end MRR from every subscription, then fits churn (Beta distribution), new deals per month
(Poisson with a damped trend), deal sizes (resampled from real deals) and the collection rate, and
plays out thousands of possible futures. You get a fan chart with 50% and 90% ranges, the ARR
distribution, the chance of hitting a target, downside risk, expected cash, and written insights,
including whether cutting churn or winning more deals matters more. Sliders for "what if churn
doubles" and so on. (It's a statistical model; the insights are generated from its numbers, not by
a language model.)

**Simulation data.** The admin can load 18 months of simulated customers from the forecast page.
Each month goes through the real services: sign-ups, billing runs, churn, renewals, seat upsells and
payments with different payment habits (prompt, slow, bad).

**Pause and resume.** Pause with an optional resume date and reason. Plans can cap the length of a
pause. Nothing is billed while paused; billing resumes it automatically on its date and bills from
that day.

**Recommendations.** Checks the live data for what to do next: overdue invoices to chase, contracts
ending soon, accounts at risk, loyal monthly customers to move to annual, upsell candidates, quotes
about to expire, drafts waiting, subscriptions due, discounts running out, plans that churn faster
than others, and customer concentration. Each shows priority, $ impact and the records involved,
with a one-click action. **Autopilot** (admin) runs all the low-risk ones in order. Everything is
logged; recommendations can be snoozed.

**Subscription black box.** Like a flight recorder: every subscription keeps an append-only log of
every billing event (lifecycle changes, invoices with their tax and discount breakdown, payments with
late flags, price changes, locks, reminders). Each entry stores the SHA-256 hash of the one before
it, so editing or deleting anything breaks the chain and the system shows where. Every subscription
can produce a printable **Flight recorder report** with an integrity seal, lifetime figures, a
billed-vs-collected chart, incidents and the full event log, plus JSON export. Customers get their own
copy (internal notes left out).

**Customer window.**

- **Timeline**: everything that has happened on their subscriptions and what's coming in the next six
  months (invoice dates with estimated amounts, renewals, resumes, price changes, lock end dates).
- **Price Change Guardian**: the admin schedules price changes with notice (Products → Price change).
  Affected customers are emailed and see exactly what changes, when, and by how much per month and
  year, plus a forecast of their next invoice and a watch list (discounts ending, billing restarting
  after a pause). The billing run applies the new price on the day.
- **Renewal Lock**: lock today's price through the next renewal. Price rises skip locked
  subscriptions until the lock ends; in return the customer can't cancel early while it's on.
- **QR pass**: a wallet-style pass per subscription. Scanning the QR opens a public check page
  (valid / paused / ended) with no prices or contact details. Codes are signed so they can't be
  forged, and reissuing a pass revokes the old one.

**Look and feel.** An intro screen (press any key or click to continue), a login page with an animated
perspective grid, an ombre purple sidebar for the internal team, and dark mode (follows your OS until
you pick one with the sun/moon button).

---

## Folder structure

```
backend/app/
  main.py                  app setup, startup (tables, small column migrations, seed, black box backfill)
  models.py                database tables
  schemas.py               request/response models
  auth.py                  password rules, hashing, login tokens, role checks
  seed_data.py             sample data
  services/
    subscription_service   lifecycle, pause/resume, renewals
    billing_service        billing runs, invoices
    discount_service       discount rules
    tax_service            tax rules
    payment_service        payments
    analytics_service      dashboard numbers
    forecast_service       Monte Carlo forecast
    simulation_data        18-month simulated history
    recommendation_service recommendations and autopilot
    blackbox               hash-chained event recorder and report data
    customer_features      timeline, price changes, renewal lock, QR pass
  routers/                 API endpoints
backend/tests/             85 tests (per brief phase, plus one file per extra)
frontend/
  templates/               index.html (the app), invoice print, black box report, pass check page
  static/                  app.js, styles.css
```

## Settings

All optional, set as environment variables.

| Variable | Default | What it's for |
|---|---|---|
| `DATABASE_URL` | `sqlite:///brightloop.db` | where the data lives |
| `SECRET_KEY` | generated into `.secret_key` | signs login tokens and QR passes |
| `APP_BASE_URL` | `http://127.0.0.1:8000` | used in reset links and QR codes; set it to your laptop's network address or the deployed URL if phones need to scan passes |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | not set | to actually send emails; without them, emails are saved and the admin can read them under **Email outbox** |
| `SEED_DEMO_DATA` | `1` | set to `0` to skip the sample data |
