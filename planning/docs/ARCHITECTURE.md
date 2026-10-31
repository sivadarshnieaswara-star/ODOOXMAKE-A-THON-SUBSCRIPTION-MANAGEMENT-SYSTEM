# Brightloop Software — System Architecture & Data Dictionary
## Odoo x Make-A-Thon Subscription Management System

---

## 1. Executive Problem Context
Brightloop Software sells cloud software, recurring business tools, and add-on services. Customers range from small monthly shops to enterprise yearly contracts. Today, Brightloop suffers from disconnected spreadsheets, forgotten renewals, manual invoice drafting, manual payment matching, and slow quarterly reporting.

The Brightloop Subscription Management System replaces these manual points of failure with a unified platform providing:
1. Automated customer signup with strict password security (>8 characters, uppercase, lowercase, special character).
2. 3-tier Role-Based Access Control (Admin, Internal Staff, Customer Portal).
3. Product catalog with configurable attribute variants (e.g., Odoo Brand Edition adding +$560 to base price).
4. Multi-frequency subscription plans (daily, weekly, monthly, yearly) carrying granular lifecycle policy flags (auto-close, early close, pause, renewal).
5. Quotation templates that auto-expand into Draft subscriptions with calculated expiry dates.
6. Automated bulk recurring billing engine with strict idempotency (no double-billing or skipped cycles).
7. Admin-only discount rules (% or fixed, minimum purchase/quantity thresholds, usage counters) auto-applied to invoices.
8. Multi-method payment collection (credit card, bank transfer, cash, UPI, Stripe) with real-time balance reconciliation to `Paid`.
9. Executive finance analytics dashboard delivering MRR, ARR, cash collection, and overdue aging reports in under 2 seconds (SLA).

---

## 2. Technical Stack
- **Backend**: Python 3.12+ with FastAPI (asynchronous, self-documenting OpenAPI at `/docs`).
- **Database & ORM**: SQLAlchemy 2.0+ with SQLite (zero-setup portable storage, sub-5ms indexed queries).
- **Environment & Dependency Management**: `uv` (lightning-fast package resolution and execution).
- **Security & Cryptography**: PBKDF2-HMAC-SHA256 (100k iterations, 16-byte unique salts, constant-time compare) and PyJWT (HMAC-SHA256 bearer tokens).
- **Frontend**: Responsive single-page web portal styled with Odoo's design aesthetic (purple `#714B67`, teal `#008784`, clean card views).

---

## 3. Relational Entity Dictionary

### 3.1 `User`
Stores authenticated users and controls access boundaries:
- `id` (Integer, Primary Key)
- `email` (String, Unique, Indexed, Not Null): User login identifier.
- `name` (String, Not Null): Full name.
- `company_name` (String, Nullable): Customer organization.
- `password_hash` (String, Not Null): Hex-encoded PBKDF2 digest.
- `password_salt` (String, Not Null): 16-byte cryptographic salt.
- `role` (String, Indexed, Not Null): `admin`, `staff`, or `customer`.
- `is_active` (Boolean, Default True): Account status.
- `reset_token` (String, Nullable, Indexed): Secure token for password recovery.
- `reset_token_expiry` (DateTime, Nullable): 1-hour expiration timestamp.
- `created_at` (DateTime): Timestamp of account creation.

### 3.2 `Product`
Base billable items:
- `id` (Integer, Primary Key)
- `name` (String, Indexed, Not Null): E.g., "Brightloop ERP Core", "CRM Pro".
- `product_type` (String, Not Null): `software`, `addon`, `service`.
- `sales_price` (Float, Not Null): Standard base selling price.
- `cost_price` (Float, Not Null): Internal unit cost.
- `notes` (Text, Nullable): Description or specifications.
- `is_active` (Boolean, Default True)

### 3.3 `ProductVariant`
Specialized attribute options:
- `id` (Integer, Primary Key)
- `product_id` (Integer, Foreign Key -> `products.id`)
- `attribute_name` (String, Not Null): E.g., "Brand", "Tier".
- `variant_value` (String, Not Null): E.g., "Odoo Brand Edition", "Standard".
- `surcharge` (Float, Default 0.0): Price markup (e.g. +$560.0).
- Computed property: `effective_price = product.sales_price + surcharge`.

### 3.4 `Plan`
Billing schedules and lifecycle rules:
- `id` (Integer, Primary Key)
- `name` (String, Not Null): E.g., "Enterprise Annual", "Pro Monthly".
- `cost` (Float, Not Null): Recurring base charge.
- `billing_frequency` (String, Not Null): `daily`, `weekly`, `monthly`, `yearly`.
- `min_quantity` (Integer, Default 1): Minimum seat or license requirement.
- `start_date`, `end_date` (Date, Nullable): Availability window.
- `auto_close_on_expiry` (Boolean, Default True): Auto-transitions to Closed when expired.
- `allow_early_close` (Boolean, Default True): Allows customer/staff cancellation before expiry.
- `allow_pause` (Boolean, Default True): Allows pausing subscription.
- `allow_renewal` (Boolean, Default True): Allows renewing after closure.

### 3.5 `QuotationTemplate` & `QuotationTemplateLine`
Reusable sales bundles:
- `QuotationTemplate`: `id`, `name`, `validity_days` (default 15), `plan_id`, `notes`.
- `QuotationTemplateLine`: `id`, `template_id`, `product_id`, `variant_id`, `quantity`, `unit_price`.

### 3.6 `Subscription` & `SubscriptionLine`
Active customer recurring contracts:
- `Subscription`:
  - `id` (Integer, Primary Key)
  - `subscription_number` (String, Unique, Indexed): Sequenced as `SUB-00001`.
  - `customer_id` (Integer, Foreign Key -> `users.id`)
  - `plan_id` (Integer, Foreign Key -> `plans.id`)
  - `start_date` (Date, Not Null)
  - `expiry_date` (Date, Nullable)
  - `payment_terms` (String, Default "Net 15"): "Immediate", "Net 15", "Net 30".
  - `status` (String, Indexed): `draft`, `quotation`, `confirmed`, `active`, `paused`, `closed`.
  - `last_billing_date` (Date, Nullable): Date of most recent invoice generation.
  - `next_billing_date` (Date, Nullable, Indexed): Next scheduled invoice date.
- `SubscriptionLine`: `id`, `subscription_id`, `product_id`, `variant_id`, `quantity`, `unit_price`, `tax_rate`, `amount`.

### 3.7 `TaxRule` & `DiscountRule`
Fiscal and incentive rules:
- `TaxRule`: `id`, `name`, `rate_percentage` (e.g. 10.0), `is_default`, `is_active`.
- `DiscountRule`: `id`, `code` (e.g. "ENTERPRISE20"), `description`, `discount_type` (`percentage`, `fixed`), `value`, `min_purchase`, `min_quantity`, `start_date`, `end_date`, `max_uses`, `current_uses`, `target_type` (`subscription`, `product`), `product_id`, `is_active`.

### 3.8 `Invoice` & `InvoiceLine`
Recurring billing statements:
- `Invoice`:
  - `id` (Integer, Primary Key)
  - `invoice_number` (String, Unique, Indexed): Sequenced as `INV-00001`.
  - `subscription_id` (Integer, Foreign Key -> `subscriptions.id`)
  - `customer_id` (Integer, Foreign Key -> `users.id`)
  - `issue_date` (Date, Not Null)
  - `due_date` (Date, Not Null)
  - `status` (String, Indexed): `draft`, `confirmed`, `paid`, `cancelled`.
  - `subtotal`, `discount_amount`, `discount_code`, `tax_amount`, `total_amount`, `balance_due`.
  - `sent_at` (DateTime, Nullable): Simulated email dispatch timestamp.
- `InvoiceLine`: `id`, `invoice_id`, `product_name`, `variant_name`, `quantity`, `unit_price`, `tax_rate`, `line_subtotal`, `line_tax`, `line_total`.

### 3.9 `Payment`
Cash collection records:
- `id` (Integer, Primary Key)
- `payment_number` (String, Unique, Indexed): Sequenced as `PAY-00001`.
- `invoice_id` (Integer, Foreign Key -> `invoices.id`)
- `customer_id` (Integer, Foreign Key -> `users.id`)
- `amount` (Float, Not Null): Collected sum.
- `payment_method` (String): `credit_card`, `bank_transfer`, `cash`, `upi`, `stripe`.
- `payment_date` (Date, Not Null)
- `note` (Text, Nullable)
