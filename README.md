# Brightloop - Subscription Management System

Our project for the Odoo x Make-A-Thon. The problem statement was to build one system for a
subscription business (Brightloop Software) that handles products, plans, subscriptions,
recurring invoices, payments and reporting, instead of spreadsheets and manual invoices.

Built with FastAPI + SQLAlchemy + SQLite on the backend and plain JS + Tailwind on the frontend.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install fastapi "uvicorn[standard]" sqlalchemy pydantic email-validator python-dateutil pyjwt jinja2 qrcode httpx pytest
.venv/bin/python run.py
```

Open http://127.0.0.1:8000. API docs are at /docs.

The first run creates `brightloop.db` and fills it with sample data so there's something to look at.
Delete the file if you want to start fresh (or run with `SEED_DEMO_DATA=0` to get just the admin account).

Logins for the sample data (there are also quick-login buttons on the login page):

- admin: admin@brightloop.com / BrightloopAdmin#2026
- staff: staff@brightloop.com / BrightloopStaff#2026
- customer: acme@corp.com / CustomerPass#2026
- customer: retail@shop.com / CustomerPass#2026

## Tests

```bash
.venv/bin/python -m pytest -q
```

There's one test per requirement more or less, split by phase. `test_phase4.py` also loads 5000
subscriptions and ~20k invoices to check the dashboard and lists still come back in under 2 seconds.

## What it does

**Accounts and roles** - sign up with email + password (password has to be more than 8 chars with
upper, lower and a special character). One account per email. Forgot password sends a reset link
that works once and expires after an hour. Three roles: admin, staff and customer. Only the admin can
add staff, and customers only ever see their own stuff.

**Products and plans** - products have a type, sales/cost price, notes and variants. A variant adds
an extra amount on top of the price (e.g. Odoo brand edition = +560). Plans have a price, billing
frequency (daily/weekly/monthly/yearly), minimum quantity, availability dates, and switches for
whether they auto-close, can be closed early, paused or renewed.

**Quotes and subscriptions** - staff can save quotation templates (plan + product lines + how many days
the quote is valid) and create a quote for a customer from one in a click. Subscriptions get numbers
like SUB-00001 and go Draft -> Quotation -> Confirmed -> Active -> Closed (can also be Paused).
Every status change is logged so you can see the history.

**Billing** - the "Run billing" button creates invoices for every subscription that's due, with the
lines, tax and totals filled in from the subscription. You can run it as many times as you want, it
won't create the same invoice twice (there's a unique constraint on subscription + period), and if
billing was missed for a few periods it catches up. Monthly billing keeps the same day of month
(31 Jan -> 28 Feb -> 31 Mar). Invoices go Draft -> Confirmed -> Paid, or Cancelled, and can be
emailed or printed.

**Discounts and taxes** - admin sets up tax rules (one default, or per product) and discount rules
(percent or fixed, min amount/quantity, start/end date, max uses, for a product or a whole
subscription). If a discount applies it's added to the next invoice automatically, and it stops once
it expires or runs out of uses. If more than one applies, the customer gets the bigger one.

**Payments** - record a payment (method, amount, date, note) against an invoice. Part payments lower
the balance, and the invoice switches to Paid when it hits zero. Customers can also pay from their
portal (the checkout is simulated, no real payment gateway).

**Dashboard** - active subscriptions, MRR, ARR, money collected, outstanding and overdue amounts,
a 12 month chart of invoiced vs collected, and a list of overdue invoices with contact details.
Can be filtered by date, plan and customer.

**Revenue forecast** - a Monte Carlo simulation fitted to the company's own history. It rebuilds
month-end MRR from every subscription, fits monthly churn (Beta distribution), new deals per month
(Poisson with a damped trend), deal sizes (resampled from real deals) and the collection rate, then
simulates a few thousand possible futures. The page shows a fan chart (50% and 90% ranges), the ARR
distribution, the chance of hitting an ARR target, downside risk, expected cash and written insights,
including whether cutting churn or winning more deals moves the number more. Sliders let you try
"what if churn doubles" and similar. The admin can load 18 months of simulated customers (sign-ups,
churn, renewals, upsells, billing and payments, all run through the normal billing engine) from that
page so there's enough history to learn from.

**Pause and resume** - a subscription can be paused with an optional resume date and a reason.
Plans can cap how long a pause lasts. Nothing is billed while paused; the billing run resumes it
automatically on its resume date and bills from that day, so the paused time is never charged.
Customers can pause and resume their own subscriptions from the portal (where the plan allows it).

**Recommendations** - a rules engine that checks the live data and suggests what to do next:
overdue invoices to chase, contracts ending within 60 days, accounts at risk (long pauses or 30+ days
overdue), loyal monthly customers to offer annual billing, upsell candidates, quotes about to expire,
draft invoices and subscriptions due for billing, discounts running out, plans that churn faster than
the rest, and customer concentration. Each one shows its priority, $ impact and the records involved,
and most have a one-click action (emails, confirming drafts, running billing). The admin can run
"autopilot", which carries out all the low-risk ones in order. Everything is logged in an activity
feed, and recommendations can be snoozed for 30 days.

**Subscription black box** - like a flight recorder, every subscription keeps an append-only log of
every important billing event: created, quoted, confirmed, activated, terms changed, paused and
resumed (with dates and reasons), renewed, closed, every invoice issued (with its tax and discount
breakdown), confirmed, sent or cancelled, every payment (flagging late ones), invoices settled, and
reminder or outreach emails. Each entry stores the SHA-256 hash of the entry before it, so changing or
deleting anything in the past breaks the chain, and the system shows where. Any subscription can
produce a printable "Flight recorder report" (save as PDF from the print dialog) with an integrity
seal, lifetime figures, a billed-vs-collected chart, an incidents list and the full event log; JSON
export is available too. Customers can download a copy for their own subscriptions (internal notes
left out). Subscriptions that existed before the recorder get their history rebuilt from existing
records on startup, marked as reconstructed.

**Customer window** - four things customers get in their portal:

- *Personal timeline*: everything that has happened on their subscriptions (from the black box,
  customer copy) and what's coming in the next six months: invoice dates with estimated amounts,
  contract ends, scheduled resumes, quote deadlines, price changes and when a Renewal Lock ends.
- *Price Change Guardian*: when the admin schedules a price change (Products → Price change, 30 days'
  notice by default), every affected subscriber is emailed and it lands in their black box. The
  Guardian page shows each change with its $ impact per month and year, the effective date, a
  forecast of the next invoice against the last one, and a watch list (discounts ending, billing
  restarting after a pause, a lock about to end). The billing run applies the new price on the day;
  negotiated prices move by the same percentage.
- *Renewal Lock*: lock today's price through the next renewal (12 months, or the next term on a
  fixed contract). Scheduled increases skip locked subscriptions until the lock ends. In return the
  customer can't cancel early while locked. Staff can release a lock.
- *QR pass*: a wallet-style pass per subscription with a signed QR code. Scanning it opens a public
  check page (valid / paused / ended, holder, plan, renewal date, no prices or contact details).
  Codes can't be forged, and reissuing a pass revokes the old code.

## Folder structure

```
backend/app/
  main.py          starts the app, creates tables, seeds data
  models.py        database tables
  schemas.py       request/response models
  auth.py          passwords, tokens, role checks
  services/        billing, discounts, taxes, payments, subscriptions, dashboard numbers,
                   forecast (Monte Carlo) and the simulation data generator
  routers/         API endpoints
  seed_data.py     sample data
backend/tests/     tests
frontend/          index.html, invoice print page, app.js, styles.css
```

## Settings (env vars, all optional)

- `DATABASE_URL` - defaults to `sqlite:///brightloop.db`
- `SECRET_KEY` - for signing login tokens; if not set one is generated into `.secret_key`
- `APP_BASE_URL` - used in the password reset link, defaults to http://127.0.0.1:8000
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` - to actually send emails.
  Without these, emails are just saved and the admin can read them under "Email outbox".
- `SEED_DEMO_DATA` - set to 0 to skip the sample data
