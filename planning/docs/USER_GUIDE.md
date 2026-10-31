# Brightloop Software — User Manual & Operations Guide
## Odoo x Make-A-Thon Edition

---

## 1. Quick Start with `uv`

### 1.1 Environment Setup
```bash
# Clone the repository
git clone https://github.com/sivadarshnieaswara-star/ODOOXMAKE-A-THON-SUBSCRIPTION-MANAGEMENT-SYSTEM.git
cd ODOOXMAKE-A-THON-SUBSCRIPTION-MANAGEMENT-SYSTEM

# Initialize environment using uv
uv venv .venv
uv pip install -r requirements.txt

# Start the application server
uv run python run.py
```
Open your browser to:
- **Interactive Web Portal**: `http://localhost:8000`
- **Interactive OpenAPI Swagger Docs**: `http://localhost:8000/docs`

### 1.2 Default Seed Accounts
| Role | Email | Password | Permissions |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin@brightloop.com` | `BrightloopAdmin#2026` | Full system control: products, variants, plans, taxes, discounts, staff accounts, executive analytics. |
| **Internal Staff** | `staff@brightloop.com` | `BrightloopStaff#2026` | Quotations, subscriptions pipeline, billing runs, invoice management, payment recording, overdue tracking. |
| **Customer** | `acme@corp.com` | `CustomerPass#2026` | Self-service portal: view own subscriptions (pause/renew/close within policy), view invoices, print PDF invoices, make payments. |

---

## 2. Administrator Guide

### 2.1 Staff Provisioning
1. Log in with an Admin account.
2. Navigate to **Staff Management**.
3. Click **Add New Staff Member**.
4. Enter full name, staff email, and a secure password compliant with the mandatory password policy (>8 characters, uppercase, lowercase, special character).
5. Only Admin accounts have access to this screen; internal staff accounts cannot create fellow staff accounts.

### 2.2 Product & Variant Management
1. Navigate to **Products & Variants**.
2. Click **Create Product** and specify the name, product type (`software`, `addon`, or `service`), sales price, cost price, and descriptive notes.
3. To add a variant with surcharge (e.g., brand edition):
   - Select the product.
   - Click **Add Variant**.
   - Set Attribute Name to `Brand` and Variant Value to `Odoo Brand Edition`.
   - Set Price Surcharge to `560.00`.
   - The system automatically computes and displays the effective price ($1,760.00).

### 2.3 Subscription Plans & Lifecycle Policies
1. Navigate to **Plans**.
2. Click **Create Plan**.
3. Choose the billing frequency (`daily`, `weekly`, `monthly`, `yearly`).
4. Set minimum quantity and optional date availability windows.
5. Configure the lifecycle policy toggles:
   - **Auto-Close on Expiry**: When enabled, the system automatically marks the contract `Closed` once the end date is reached.
   - **Allow Early Close**: Allows customer or staff to terminate the subscription prior to the end date.
   - **Allow Pause**: Permits pausing billing temporarily.
   - **Allow Renewal**: Allows expired or closed subscriptions to be renewed into a new quote.

### 2.4 Tax & Discount Rules
1. Navigate to **Discounts & Taxes**.
2. Create standard tax rules (e.g. `Standard VAT 10%`, `GST 18%`).
3. Create discount rules:
   - Choose percentage (e.g., 20%) or fixed amount (e.g., $100 off).
   - Set minimum purchase amount or minimum seat quantity threshold.
   - Set start and end validity dates.
   - Set maximum usage limit (e.g., first 50 customers).
   - Choose scope: applies to the whole subscription or a specific product line.
   - The engine automatically applies the highest qualifying discount to due invoices on billing day.

---

## 3. Internal Staff Guide

### 3.1 Quotation Templates & Subscription Creation
1. Navigate to **Quotations & Subscriptions**.
2. To create a quotation:
   - Select **New from Template** and choose a template (e.g., `Enterprise Annual Bundle`).
   - Select the customer.
   - Line items, pricing, variant surcharges, and validity dates are automatically populated.
3. Review line items and click **Send Quotation** (advances state to `Quotation`).
4. Once the customer accepts, click **Confirm** (state: `Confirmed`), then **Activate** (state: `Active`).

### 3.2 Billing Day Execution
1. On billing day, navigate to **Recurring Billing**.
2. Click **Run Billing Day Batch**.
3. The system scans all active subscriptions where `next_billing_date <= today`:
   - Auto-generates Draft invoices (`INV-XXXXX`).
   - Automatically computes taxes and applies active discount rules.
   - Guarantees idempotency: running the batch multiple times never produces duplicate invoices.
   - Automatically advances each subscription's `next_billing_date`.

### 3.3 Payments & Overdue Tracking
1. Navigate to **Invoices**.
2. To record a payment:
   - Open the invoice.
   - Click **Record Payment**.
   - Select payment method (`credit_card`, `bank_transfer`, `cash`, `upi`, `stripe`), enter amount, date, and note.
   - The system immediately recalculates the balance due. When balance reaches $0.00, the invoice automatically switches to `Paid`.
3. To follow up on late payments, open the **Overdue Invoices** tab to see unpaid invoices past their due date with customer contact details.

---

## 4. Customer Self-Service Portal Guide

Customers log into the dedicated self-service portal:
1. **View Active Subscriptions**: Customers can see their active software licenses, renew dates, and plan details without needing to email support.
2. **Manage Subscriptions**:
   - Pause or resume active subscriptions (if allowed by the plan's `allow_pause` policy).
   - Request renewal (if allowed by the plan's `allow_renewal` policy).
3. **Invoices & Payments**:
   - View complete invoice history.
   - Download or print formatted invoices for accounting.
   - Pay outstanding balances directly via integrated payment options.
4. **Data Isolation**: Customers can strictly view only their own records; other customers' data is completely inaccessible.

---

## 5. Executive Financial Analytics (< 2.0s SLA)

Accessible to Admin and Staff under **Finance Dashboard**:
- **Active Subscriptions**: Total active contracts in the system.
- **MRR (Monthly Recurring Revenue)**: Normalized recurring monthly cash inflow across all billing frequencies.
- **ARR (Annual Recurring Revenue)**: $MRR \times 12$.
- **Total Revenue Collected**: Cash collected to date.
- **Total Outstanding Dues**: Confirmed invoice balances awaiting payment.
- **Overdue Invoices Summary**: Real-time count and dollar value of late invoices.
- **Query Performance**: Monitored with live millisecond timing (benchmarked at <15ms, well under the 2-second target).
