# Requirements: Brightloop Subscription Management System

## Core Functional Requirements

### Authentication & Access Control (AUTH & RBAC)
- **REQ-AUTH-01**: User registration must enforce unique emails and strict password requirements: more than 8 characters, at least one uppercase letter, at least one lowercase letter, and at least one special character.
- **REQ-AUTH-02**: Self-service password reset requesting a token sent to registered email and allowing password update.
- **REQ-RBAC-01**: Three distinct roles:
  - `Admin`: Full control over products, plans, taxes, discounts, staff accounts, and financial metrics.
  - `Staff`: Day-to-day handling with limited access (quotes, subscriptions, invoices, payments, overdue tracking); cannot add new staff.
  - `Customer`: Limited portal view showing only their own subscriptions and invoices.

### Products & Variants (PROD)
- **REQ-PROD-01**: Cataloging products with name, type (software, add-on, service), sales price, cost price, and notes.
- **REQ-PROD-02**: Attribute variants for products, supporting price surcharges (e.g. choosing "Odoo" brand adds 560 to price).

### Plans & Policies (PLAN)
- **REQ-PLAN-01**: Plans define cost, billing frequency (daily, weekly, monthly, yearly), minimum quantity, and availability date window.
- **REQ-PLAN-02**: Per-plan lifecycle policies configurable by admin: auto-close on expiry, allow early close, allow pause, and allow renewal.

### Quotations & Subscriptions (SUB)
- **REQ-SUB-01**: Quotation templates with pre-configured plan and product lines valid for a defined number of days.
- **REQ-SUB-02**: Subscription creation with sequential number (`SUB-XXXXX`), customer, plan, start/expiry dates, payment terms, and line items.
- **REQ-SUB-03**: Workflow progression: `Draft` -> `Quotation` -> `Confirmed` -> `Active` -> `Closed` (with `Paused` state), visible to the entire team.

### Billing Engine & Invoicing (BILL)
- **REQ-BILL-01**: Automated recurring invoice generation when subscriptions become due (`next_billing_date <= today`).
- **REQ-BILL-02**: Idempotent billing preventing double-billing or skipped cycles for any billing period.
- **REQ-BILL-03**: Automatic line-by-line tax calculation based on admin-defined tax rules.
- **REQ-BILL-04**: Invoice workflow: `Draft` -> `Confirmed` -> `Paid` (or `Cancelled`), with send and print capabilities.

### Discount Engine (DISC)
- **REQ-DISC-01**: Admin-only discount rules with fixed amount or percentage, minimum purchase or quantity thresholds, start and end validity dates, and usage limits.
- **REQ-DISC-02**: Automatic application to eligible invoices (product-specific or whole subscription) and automatic cessation upon expiration or limit exhaustion.

### Payments & Financial Analytics (PAY & FIN)
- **REQ-PAY-01**: Payment recording against invoices with method, amount, date, and note; auto-reconciles balance due to `Paid`.
- **REQ-PAY-02**: Outstanding balance and overdue invoice identification.
- **REQ-FIN-01**: Executive finance dashboard delivering active subscriptions, MRR, ARR, revenue collected, and overdue invoice tracking in under 2 seconds.
- **REQ-PORTAL-01**: Customer self-service portal to view active subscriptions, manage plan status (pause/renew/close within policy), view invoices, and make payments.
