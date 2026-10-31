# Brightloop Software - Subscription Management System

## What This Is

A unified subscription management and recurring billing software platform for Brightloop Software (Odoo x Make-A-Thon). It manages the entire lifecycle of a subscription business: product and variant cataloging, multi-frequency plans, quotation-to-subscription workflows, automated recurring invoicing with dynamic tax and discount rules, multi-method payment reconciliation, self-service customer portal, and executive financial analytics (MRR/ARR/overdue tracking).

## Core Value

To serve as the reliable, automated digital backbone for Brightloop Software that ensures zero missed renewals, accurate recurring invoices without double-billing or skipped cycles, seamless payment matching, and sub-2-second financial reporting.

## Business Context

- **Customer**: B2B and B2C clients ranging from small monthly shops to large yearly enterprise contracts.
- **Revenue model**: Recurring billing (daily, weekly, monthly, yearly), tiered licenses, and product variant add-ons.
- **Success metric**: 100% automated invoice generation accuracy, zero double-billing, and instant (<2s) financial visibility.

## Requirements

### Validated

(None yet — milestone in progress)

### Active

- [ ] **AUTH & RBAC**: Unique email signup, strict password policy (>8 chars, uppercase, lowercase, special char), password reset flow, and 3-tier RBAC (Admin, Staff, Customer).
- [ ] **PRODUCTS & VARIANTS**: Product catalog (sales price, cost price, notes) with configurable attribute variants (e.g., Odoo Brand Edition +$560 surcharge).
- [ ] **PLANS & LIFECYCLE POLICIES**: Flexible billing intervals (daily, weekly, monthly, yearly), minimum quantities, date ranges, and per-plan lifecycle toggles (auto-close on expiry, early close, pause, renewal).
- [ ] **QUOTATIONS & SUBSCRIPTIONS**: Quotation templates with preset lines and validity duration, sequential numbering (`SUB-XXXXX`), status progression (`Draft` -> `Quotation` -> `Confirmed` -> `Active` -> `Closed`).
- [ ] **AUTOMATED BILLING ENGINE**: Bulk recurring billing for due subscriptions, line-by-line tax calculation from admin rules, automated discount application, idempotency to prevent double-billing.
- [ ] **DISCOUNT SYSTEM**: Admin-only rules (percentage or fixed amount, min purchase or quantity thresholds, validity windows, max usage limits, product or subscription scope) auto-applied to invoices.
- [ ] **PAYMENT TRACKING & RECONCILIATION**: Payment recording by method (credit card, bank transfer, cash, upi, stripe), date, and note; auto-reconciliation of balance due to Paid status.
- [ ] **FINANCE REPORTING & PORTAL**: Sub-2-second analytics dashboard for active subscriptions, MRR, ARR, revenue collected, and overdue invoice tracking; dedicated Customer Self-Service Portal.

### Out of Scope

- External physical card swipe terminals (handled via simulated payment gateways / payment recording).
- Multi-currency conversion rates (single base currency USD / standard currency for hackathon scope).
