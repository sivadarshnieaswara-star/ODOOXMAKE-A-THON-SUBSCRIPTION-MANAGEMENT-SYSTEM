# Roadmap: Brightloop Subscription Management System

## Overview

This roadmap defines the 4 phases required to build, verify, and deliver the unified subscription management and recurring billing platform for Brightloop Software according to the Odoo x Make-A-Thon challenge specification.

## Phases

- [ ] **Phase 1: Foundation, Auth, RBAC & Product Catalog** - Strict authentication, role-based access control (Admin, Staff, Customer), and product catalog with variants and surcharges.
- [ ] **Phase 2: Plans, Quotations & Subscription Lifecycle** - Recurring plans with lifecycle policies, quotation templates, and full subscription state machine.
- [ ] **Phase 3: Automated Recurring Billing, Taxes & Discounts** - Bulk billing engine, idempotent invoice generation, dynamic tax calculation, and admin discount rule evaluation.
- [ ] **Phase 4: Payments, Customer Portal & Finance Analytics Dashboard** - Payment reconciliation, customer self-service portal, overdue tracking, and sub-2-second finance analytics.

## Phase Details

### Phase 1: Foundation, Auth, RBAC & Product Catalog
**Goal**: Deliver secure authentication with the required password strength policy, 3-tier RBAC, password reset token mechanism, and product catalog supporting variants with price surcharges.
**Depends on**: Nothing (first phase)
**Requirements**: [REQ-AUTH-01, REQ-AUTH-02, REQ-RBAC-01, REQ-PROD-01, REQ-PROD-02]
**Success Criteria** (what must be TRUE):
  1. User cannot register with password <= 8 chars or missing uppercase/lowercase/special characters.
  2. Only Admin role can create new Staff members; Staff and Customers receive 403 Forbidden.
  3. Products can be created with base price and variant attributes (e.g. Odoo brand adding 560 to price).
  4. Password reset token can be requested and used to update account password.
**Plans**: 2 plans

Plans:
- [ ] 01-01: Foundation, Database Models, Schemas & Auth with Strict Password Policy
- [ ] 01-02: Product & Variant Catalog APIs, Admin Staff Provisioning & Verification Suite

### Phase 2: Plans, Quotations & Subscription Lifecycle
**Goal**: Implement subscription plans with configurable lifecycle policies, quotation templates, and the full subscription workflow from draft to closed.
**Depends on**: Phase 1
**Requirements**: [REQ-PLAN-01, REQ-PLAN-02, REQ-SUB-01, REQ-SUB-02, REQ-SUB-03]
**Success Criteria** (what must be TRUE):
  1. Admin can configure plans with daily, weekly, monthly, and yearly frequencies, minimum quantities, date ranges, and lifecycle policies.
  2. Sales quotes can be generated from quotation templates pre-filling lines and expiration dates.
  3. Subscriptions follow the explicit workflow: Draft -> Quotation -> Confirmed -> Active -> Closed.
  4. Plan policies (e.g., allow_pause, allow_early_close, allow_renewal) strictly block unauthorized state transitions.
**Plans**: 2 plans

Plans:
- [ ] 02-01: Recurring Plans & Quotation Templates Engine
- [ ] 02-02: Subscription Lifecycle State Machine & Policy Enforcement

### Phase 3: Automated Recurring Billing, Taxes & Discounts
**Goal**: Build the recurring billing engine capable of processing due subscriptions in bulk, calculating taxes, applying eligible discount rules, and generating invoices without double-billing.
**Depends on**: Phase 2
**Requirements**: [REQ-BILL-01, REQ-BILL-02, REQ-BILL-03, REQ-BILL-04, REQ-DISC-01, REQ-DISC-02]
**Success Criteria** (what must be TRUE):
  1. Billing day bulk run identifies all due active subscriptions and generates accurate draft invoices.
  2. System enforces idempotency: running billing twice on the same day never creates duplicate invoices or skips subscriptions.
  3. Admin discount rules (percentage or fixed, min purchase/quantity, usage counters) automatically apply to eligible invoices and cease when expired.
  4. Taxes are automatically computed line-by-line based on admin tax rules.
**Plans**: 2 plans

Plans:
- [ ] 03-01: Admin Tax Rules & Discount Evaluation Engine
- [ ] 03-02: Automated Bulk Recurring Billing Engine & Invoice Lifecycle

### Phase 4: Payments, Customer Portal & Finance Analytics Dashboard
**Goal**: Implement payment recording and auto-reconciliation, customer self-service portal, overdue invoice chase tracking, and executive finance analytics responding in under 2 seconds.
**Depends on**: Phase 3
**Requirements**: [REQ-PAY-01, REQ-PAY-02, REQ-FIN-01, REQ-PORTAL-01]
**Success Criteria** (what must be TRUE):
  1. Payments can be recorded against invoices with method, amount, date, and note, automatically marking invoice as Paid upon full balance settlement.
  2. Customers can log in to a dedicated portal to view only their own subscriptions and invoices.
  3. Finance lead dashboard accurately aggregates Active Subscriptions, MRR, ARR, Total Revenue, and Overdue Invoices in under 2 seconds.
  4. Overdue invoices are highlighted with due dates and customer contact information.
**Plans**: 2 plans

Plans:
- [ ] 04-01: Payment Recording, Auto-Reconciliation & Overdue Invoice Tracking
- [ ] 04-02: Customer Self-Service Portal & High-Speed Executive Finance Analytics (<2s SLA)
