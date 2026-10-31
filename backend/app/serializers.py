"""Turn ORM objects into the response schemas (adds names and computed fields)."""
from datetime import date

from .models import Invoice, Payment, QuotationTemplate, Subscription, User
from .services.subscription_service import allowed_actions


def sub_out(sub: Subscription, viewer: User, detail: bool = True) -> dict:
    return {
        "id": sub.id, "subscription_number": sub.subscription_number,
        "customer_id": sub.customer_id, "customer_name": sub.customer.company_name or sub.customer.name,
        "customer_email": sub.customer.email, "plan_id": sub.plan_id, "plan_name": sub.plan.name,
        "billing_frequency": sub.plan.billing_frequency, "start_date": sub.start_date,
        "expiry_date": sub.expiry_date, "payment_terms": sub.payment_terms, "status": sub.status,
        "quotation_valid_until": sub.quotation_valid_until, "last_billing_date": sub.last_billing_date,
        "paused_at": sub.paused_at, "resume_on": sub.resume_on, "pause_reason": sub.pause_reason,
        "max_pause_days": sub.plan.max_pause_days, "price_lock_until": sub.price_lock_until, "price_locked_at": sub.price_locked_at,
        "next_billing_date": sub.next_billing_date, "notes": sub.notes,
        "recurring_amount": sub.recurring_amount, "allowed_actions": allowed_actions(sub, viewer.role),
        "lines": [{
            "id": l.id, "product_id": l.product_id, "product_name": l.product.name, "variant_id": l.variant_id,
            "variant_label": l.variant.label if l.variant else None, "quantity": l.quantity,
            "unit_price": l.unit_price, "tax_rate": l.tax_rate, "amount": l.amount, "tax_amount": l.tax_amount,
        } for l in sub.lines] if detail else [],
        "events": list(sub.events) if detail else [],
    }


def payment_out(p: Payment) -> dict:
    return {
        "id": p.id, "payment_number": p.payment_number, "invoice_id": p.invoice_id,
        "invoice_number": p.invoice.invoice_number, "customer_id": p.customer_id,
        "customer_name": p.customer.company_name or p.customer.name, "amount": p.amount,
        "payment_method": p.payment_method, "payment_date": p.payment_date, "note": p.note,
        "recorded_by": p.recorded_by,
    }


def invoice_out(inv: Invoice, detail: bool = True, today: date | None = None) -> dict:
    today = today or date.today()
    overdue = inv.status == "confirmed" and inv.balance_due > 0 and inv.due_date < today
    return {
        "id": inv.id, "invoice_number": inv.invoice_number, "subscription_id": inv.subscription_id,
        "subscription_number": inv.subscription.subscription_number, "customer_id": inv.customer_id,
        "customer_name": inv.customer.company_name or inv.customer.name, "customer_email": inv.customer.email,
        "period_start": inv.period_start, "period_end": inv.period_end, "issue_date": inv.issue_date,
        "due_date": inv.due_date, "status": inv.status, "subtotal": inv.subtotal,
        "discount_amount": inv.discount_amount, "discount_code": inv.discount_code, "tax_amount": inv.tax_amount,
        "total_amount": inv.total_amount, "balance_due": inv.balance_due, "is_overdue": overdue,
        "days_overdue": (today - inv.due_date).days if overdue else 0, "sent_at": inv.sent_at,
        "paid_at": inv.paid_at, "notes": inv.notes,
        "lines": list(inv.lines) if detail else [],
        "payments": [payment_out(p) for p in inv.payments] if detail else [],
    }


def template_out(t: QuotationTemplate) -> dict:
    return {
        "id": t.id, "name": t.name, "validity_days": t.validity_days, "contract_months": t.contract_months,
        "plan_id": t.plan_id, "plan_name": t.plan.name, "payment_terms": t.payment_terms, "notes": t.notes,
        "lines": [{
            "id": l.id, "product_id": l.product_id, "variant_id": l.variant_id, "quantity": l.quantity,
            "unit_price": l.unit_price, "product_name": l.product.name,
            "variant_label": l.variant.label if l.variant else None,
        } for l in t.lines],
    }
