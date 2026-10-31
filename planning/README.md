# Brightloop Software - Subscription Management System

Unified software platform to manage plans, subscriptions, and recurring billing for Brightloop Software, built for the Odoo x Make-A-Thon.

## Key Features
- **Strict Authentication & 3-Tier RBAC**: Admin, Internal Staff, and Customer Self-Service Portal.
- **Product & Variant Catalog**: Software, add-ons, and brand variants with surcharges (e.g. Odoo brand +$560).
- **Flexible Subscription Plans**: Daily, weekly, monthly, and yearly billing intervals with lifecycle policy controls (auto-close, early close, pause, renewal).
- **Quotation to Subscription Workflow**: Quotation templates and state progression (`Draft` -> `Quotation` -> `Confirmed` -> `Active` -> `Closed`).
- **Automated Recurring Billing Engine**: Idempotent billing runs, auto tax computation, and automated discount rule application without manual overhead.
- **Payment Reconciliation**: Multi-method payments (card, bank transfer, cash, upi, stripe) and real-time invoice balance tracking.
- **Executive Finance Analytics**: Real-time sub-2-second queries for active subscriptions, MRR, ARR, revenue collected, and overdue invoice tracking.

## Technology Stack
- **Backend**: FastAPI, SQLAlchemy, SQLite, Pydantic, PyJWT, Python 3.12+
- **Package & Environment Management**: `uv`
- **Testing**: `pytest`, `httpx`

## Running the Application
```bash
# Setup environment
uv venv .venv
uv pip install -r requirements.txt

# Run the app
uv run python run.py
```
