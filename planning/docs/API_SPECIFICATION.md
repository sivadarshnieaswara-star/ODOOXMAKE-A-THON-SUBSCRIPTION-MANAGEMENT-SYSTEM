# Brightloop Software — REST API Specification
## OpenAPI 3.0 Endpoints Reference

---

## 1. Authentication & RBAC (`/api/auth`)

### 1.1 `POST /api/auth/register`
Creates a customer account. Validates email uniqueness and password complexity.
- **Request Body**:
  ```json
  {
    "email": "customer@acme.com",
    "password": "CompliantPassword123!",
    "name": "Jane Doe",
    "company_name": "Acme Corp"
  }
  ```
- **Password Policy Enforced**:
  - Length > 8 characters (at least 9 chars).
  - At least 1 uppercase letter (`[A-Z]`).
  - At least 1 lowercase letter (`[a-z]`).
  - At least 1 special character (`[^A-Za-z0-9]`).
- **Responses**:
  - `201 Created`: Returns JWT `access_token` and `user` object.
  - `400 Bad Request`: Returns specific error if email is already registered or password fails complexity rules.

### 1.2 `POST /api/auth/login`
Authenticates user and returns JWT token.
- **Request Body**:
  ```json
  {
    "email": "admin@brightloop.com",
    "password": "BrightloopAdmin#2026"
  }
  ```
- **Responses**:
  - `200 OK`: `{"access_token": "...", "token_type": "bearer", "user": {...}}`
  - `401 Unauthorized`: Invalid credentials.

### 1.3 `GET /api/auth/me`
Retrieves currently authenticated user profile and assigned role (`admin`, `staff`, `customer`).
- **Headers**: `Authorization: Bearer <token>`
- **Responses**:
  - `200 OK`: User profile object.

### 1.4 `POST /api/auth/forgot-password`
Requests password reset link/token.
- **Request Body**: `{"email": "customer@acme.com"}`
- **Responses**:
  - `200 OK`: Returns confirmation and generates a 1-hour secure reset token.

### 1.5 `POST /api/auth/reset-password`
Resets account password using a valid token.
- **Request Body**:
  ```json
  {
    "token": "d7a4f91c...",
    "new_password": "NewCompliantPassword123!"
  }
  ```
- **Security Invariants**:
  - Verifies token exists and `reset_token_expiry > now()`.
  - Enforces `validate_password_strength` on `new_password`.
  - Nullifies `reset_token` and `reset_token_expiry` immediately to prevent token replay attacks.

---

## 2. Staff Management (`/api/staff`) — Admin Only

### 2.1 `POST /api/staff`
Provisions an internal staff member. Strictly restricted to `Admin`.
- **Headers**: `Authorization: Bearer <admin_token>`
- **Request Body**:
  ```json
  {
    "email": "sarah.ops@brightloop.com",
    "name": "Sarah Connor",
    "password": "StaffSecret#2026",
    "role": "staff"
  }
  ```
- **Responses**:
  - `201 Created`: Staff user profile.
  - `403 Forbidden`: If called by non-admin (Staff or Customer).

### 2.2 `GET /api/staff`
Lists all internal staff members. Restricted to `Admin`.

---

## 3. Product & Variant Catalog (`/api/products`)

### 3.1 `GET /api/products`
Lists all active products with their variant options and surcharges.
- **Access**: Public / Authenticated (Admin, Staff, Customer).

### 3.2 `POST /api/products`
Creates a product. Strictly restricted to `Admin`.
- **Request Body**:
  ```json
  {
    "name": "Brightloop ERP Cloud",
    "product_type": "software",
    "sales_price": 1200.00,
    "cost_price": 400.00,
    "notes": "Full-suite enterprise resource planning module."
  }
  ```

### 3.3 `POST /api/products/{id}/variants`
Adds attribute variant with price surcharge. Strictly restricted to `Admin`.
- **Request Body**:
  ```json
  {
    "attribute_name": "Brand",
    "variant_value": "Odoo Brand Edition",
    "surcharge": 560.00
  }
  ```
- **Computed Value**: `effective_price = 1200.00 + 560.00 = 1760.00`.

---

## 4. Plans & Policies (`/api/plans`)

### 4.1 `GET /api/plans`
Lists all active subscription plans.

### 4.2 `POST /api/plans`
Creates a recurring plan with policy governance. Strictly restricted to `Admin`.
- **Request Body**:
  ```json
  {
    "name": "Enterprise Annual Tier",
    "cost": 15000.00,
    "billing_frequency": "yearly",
    "min_quantity": 5,
    "auto_close_on_expiry": true,
    "allow_early_close": false,
    "allow_pause": true,
    "allow_renewal": true
  }
  ```

---

## 5. Quotation Templates (`/api/templates`)

### 5.1 `GET /api/templates`
Lists available quotation templates. Accessible to `Admin` and `Staff`.

### 5.2 `POST /api/templates`
Creates a reusable quotation template with pre-configured lines.
- **Request Body**:
  ```json
  {
    "name": "Starter Small Business Bundle",
    "validity_days": 15,
    "plan_id": 1,
    "lines": [
      {"product_id": 1, "variant_id": 1, "quantity": 1, "unit_price": 1760.00},
      {"product_id": 2, "variant_id": null, "quantity": 5, "unit_price": 45.00}
    ]
  }
  ```

### 5.3 `POST /api/templates/{id}/instantiate`
Instantiates a new `Draft` subscription from a template for a given customer.

---

## 6. Subscriptions (`/api/subscriptions`)

### 6.1 `GET /api/subscriptions`
Lists subscriptions.
- **Data Scoping**:
  - `Customer`: Returns only subscriptions belonging to the calling user.
  - `Admin` & `Staff`: Returns all subscriptions; supports filters by `status`, `plan_id`, and `customer_id`.

### 6.2 `POST /api/subscriptions`
Creates a subscription with custom lines (`require_staff_or_admin`). Generates ID formatted as `SUB-00001`.

### 6.3 `POST /api/subscriptions/{id}/transition`
Advances subscription through the state machine:
- `draft` -> `quotation` -> `confirmed` -> `active` -> `closed`
- `active` <-> `paused`
- Validates plan policies (`allow_pause`, `allow_early_close`, `allow_renewal`).

---

## 7. Recurring Billing & Invoices (`/api/billing` & `/api/invoices`)

### 7.1 `POST /api/billing/run-recurring`
Executes bulk billing run for all due subscriptions (`next_billing_date <= today`).
- **Idempotency**: Prevents double-billing for the same billing date.
- **Auto-Calculates**: Line taxes and eligible discount rules.
- **Advances**: `next_billing_date` based on plan frequency.

### 7.2 `GET /api/invoices`
Lists invoices. Customers see only their own invoices; Staff and Admin see all.

### 7.3 `POST /api/invoices/{id}/status`
Transitions invoice: `draft` -> `confirmed` -> `cancelled`.

### 7.4 `GET /api/invoices/{id}/print`
Returns clean, printable HTML document styled for browser print or PDF export.

---

## 8. Payments & Reconciliation (`/api/payments`)

### 8.1 `POST /api/payments`
Records a payment against an invoice (`PAY-00001`).
- **Request Body**:
  ```json
  {
    "invoice_id": 1,
    "amount": 1760.00,
    "payment_method": "credit_card",
    "note": "Stripe transaction id: ch_3N..."
  }
  ```
- **Reconciliation Effect**:
  - Decrements `invoice.balance_due`.
  - If `balance_due == 0.0`, automatically updates `invoice.status = "paid"`.

### 8.2 `GET /api/invoices/overdue`
Returns list of all confirmed invoices where `balance_due > 0` and `due_date < today`.

---

## 9. Executive Finance Analytics (`/api/analytics`) — SLA < 2s

### 9.1 `GET /api/analytics/overview`
Delivers consolidated executive KPIs:
- **Response**:
  ```json
  {
    "active_subscriptions_count": 142,
    "mrr": 58450.00,
    "arr": 701400.00,
    "total_revenue_collected": 412300.00,
    "total_outstanding_amount": 34200.00,
    "overdue_invoices_count": 8,
    "overdue_amount": 9400.00,
    "response_time_ms": 8.4
  }
  ```
