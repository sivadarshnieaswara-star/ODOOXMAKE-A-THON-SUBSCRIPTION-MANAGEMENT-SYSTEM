from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import PAYMENT_TERMS, DiscountRule, Invoice, InvoiceLine, Subscription, User
from . import blackbox
from .common import next_number, send_email
from .discount_service import DraftLine, best_discount
from .subscription_service import auto_close_expired, auto_resume_due, next_period_start
from .tax_service import default_tax_rate, tax_rate_for_product

MAX_CATCH_UP_PERIODS = 400  # safety valve for very old daily subscriptions


def _draft_lines(db: Session, sub: Subscription) -> list[dict]:
    """Invoice lines copied from the subscription; taxes use the admin's current tax rules."""
    if not sub.lines:
        return [dict(product_id=None, product_name=sub.plan.name, variant_name=None, quantity=1,
                     unit_price=sub.plan.cost, tax_rate=default_tax_rate(db))]
    return [dict(product_id=l.product_id, product_name=l.product.name,
                 variant_name=l.variant.label if l.variant else None, quantity=l.quantity,
                 unit_price=l.unit_price, tax_rate=tax_rate_for_product(db, l.product))
            for l in sub.lines]


def build_invoice(db: Session, sub: Subscription, period_start: date, period_end: date,
                  auto_confirm: bool = False) -> Invoice:
    drafts = _draft_lines(db, sub)
    for d in drafts:
        d["subtotal"] = round(d["quantity"] * d["unit_price"], 2)
    subtotal = round(sum(d["subtotal"] for d in drafts), 2)

    discount = best_discount(db, sub.id, [DraftLine(d["product_id"], d["quantity"], d["subtotal"]) for d in drafts],
                             period_start)
    per_line = discount.per_line if discount else [0.0] * len(drafts)

    lines, tax_total = [], 0.0
    for d, disc in zip(drafts, per_line):
        taxable = max(0.0, round(d["subtotal"] - disc, 2))
        line_tax = round(taxable * d["tax_rate"] / 100.0, 2)
        tax_total += line_tax
        lines.append(InvoiceLine(
            product_name=d["product_name"], variant_name=d["variant_name"], quantity=d["quantity"],
            unit_price=d["unit_price"], tax_rate=d["tax_rate"], line_subtotal=d["subtotal"],
            line_discount=disc, line_tax=line_tax, line_total=round(taxable + line_tax, 2),
        ))
    discount_amount = discount.amount if discount else 0.0
    total = round(subtotal - discount_amount + tax_total, 2)

    inv = Invoice(
        invoice_number=next_number(db, "invoice"), subscription=sub, customer_id=sub.customer_id,
        period_start=period_start, period_end=period_end, issue_date=period_start,
        due_date=period_start + timedelta(days=PAYMENT_TERMS.get(sub.payment_terms, 30)),
        status="confirmed" if auto_confirm else "draft",
        subtotal=subtotal, discount_amount=discount_amount,
        discount_code=discount.rule.code if discount else None,
        discount_rule_id=discount.rule.id if discount else None,
        tax_amount=round(tax_total, 2), total_amount=total, balance_due=total, lines=lines,
    )
    if discount:
        discount.rule.current_uses += 1
    db.add(inv)
    blackbox.record(sub, "invoice_issued", f"Invoice {inv.invoice_number} issued for {period_start} to {period_end}"
                    + (f", {discount.rule.code} discount applied" if discount else ""), on=period_start, amount=total,
                    data={"invoice": inv.invoice_number, "period": [period_start, period_end], "due": inv.due_date,
                          "subtotal": subtotal, "discount": discount_amount, "discount_code": inv.discount_code,
                          "tax": inv.tax_amount, "status": inv.status,
                          "lines": [{"product": l.product_name, "qty": l.quantity, "unit_price": l.unit_price,
                                     "tax_rate": l.tax_rate, "total": l.line_total} for l in lines]})
    return inv


def run_billing(db: Session, as_of: date | None = None, auto_confirm: bool = False) -> dict:
    """Bill every active subscription that is due on or before `as_of`.

    Idempotent: each (subscription, period_start) is invoiced at most once, enforced both by a
    lookup and by a unique constraint, and next_billing_date only moves forward. Missed periods
    are caught up so nothing is skipped; billing stops at the subscription's expiry date."""
    as_of = as_of or date.today()
    resumed = auto_resume_due(db, as_of)   # scheduled resumes first, so they're billed from their resume date
    due = db.scalars(
        select(Subscription)
        .where(Subscription.status == "active", Subscription.next_billing_date <= as_of)
        .order_by(Subscription.id)
    ).all()

    created, skipped = [], 0
    for sub in due:
        freq = sub.plan.billing_frequency
        for _ in range(MAX_CATCH_UP_PERIODS):
            start = sub.next_billing_date
            if start is None or start > as_of or (sub.expiry_date and start > sub.expiry_date):
                break
            end = next_period_start(sub.start_date, start, freq) - timedelta(days=1)
            if sub.expiry_date and end > sub.expiry_date:
                end = sub.expiry_date
            exists = db.scalar(select(Invoice.id).where(Invoice.subscription_id == sub.id,
                                                        Invoice.period_start == start))
            if exists:
                skipped += 1
            else:
                try:
                    with db.begin_nested():
                        inv = build_invoice(db, sub, start, end, auto_confirm)
                    created.append(inv.invoice_number)
                except IntegrityError:  # another run billed this period concurrently
                    skipped += 1
            sub.last_billing_date = start
            sub.next_billing_date = next_period_start(sub.start_date, start, freq)
        if sub.expiry_date and sub.next_billing_date and sub.next_billing_date > sub.expiry_date:
            sub.next_billing_date = None  # fully billed for its term

    closed = auto_close_expired(db, as_of)
    db.commit()
    return dict(as_of=as_of, subscriptions_scanned=len(due), invoices_created=len(created),
                invoice_numbers=created, subscriptions_closed=closed, skipped_existing=skipped,
                subscriptions_resumed=resumed)


def bill_now(db: Session, sub: Subscription, auto_confirm: bool = False) -> Invoice:
    """Invoice the next due period of one subscription right away."""
    if sub.status != "active" or sub.next_billing_date is None:
        raise HTTPException(400, "Subscription has nothing left to bill")
    start = sub.next_billing_date
    if db.scalar(select(Invoice.id).where(Invoice.subscription_id == sub.id, Invoice.period_start == start)):
        raise HTTPException(400, f"Period starting {start} is already invoiced")
    end = next_period_start(sub.start_date, start, sub.plan.billing_frequency) - timedelta(days=1)
    if sub.expiry_date and end > sub.expiry_date:
        end = sub.expiry_date
    inv = build_invoice(db, sub, start, end, auto_confirm)
    sub.last_billing_date = start
    nxt = next_period_start(sub.start_date, start, sub.plan.billing_frequency)
    sub.next_billing_date = None if sub.expiry_date and nxt > sub.expiry_date else nxt
    db.flush()
    return inv


# ---------- Invoice lifecycle: Draft -> Confirmed -> Paid (or Cancelled) ----------
def confirm_invoice(inv: Invoice) -> Invoice:
    if inv.status != "draft":
        raise HTTPException(400, f"Only draft invoices can be confirmed (this one is {inv.status})")
    inv.status = "confirmed"
    inv.balance_due = inv.total_amount
    blackbox.record(inv.subscription, "invoice_confirmed", f"Invoice {inv.invoice_number} confirmed; {inv.balance_due:,.2f} due by {inv.due_date}",
                    amount=inv.total_amount, data={"invoice": inv.invoice_number, "due": inv.due_date})
    return inv


def cancel_invoice(db: Session, inv: Invoice) -> Invoice:
    if inv.status not in ("draft", "confirmed"):
        raise HTTPException(400, f"A {inv.status} invoice cannot be cancelled")
    if inv.payments:
        raise HTTPException(400, "Invoice has payments recorded against it and cannot be cancelled")
    inv.status = "cancelled"
    inv.balance_due = 0.0
    blackbox.record(inv.subscription, "invoice_cancelled", f"Invoice {inv.invoice_number} cancelled", amount=inv.total_amount,
                    data={"invoice": inv.invoice_number, "discount_returned": inv.discount_code})
    if inv.discount_rule_id:  # give the discount use back
        rule = db.get(DiscountRule, inv.discount_rule_id)
        if rule and rule.current_uses > 0:
            rule.current_uses -= 1
    return inv


def send_invoice(db: Session, inv: Invoice) -> Invoice:
    if inv.status == "draft":
        confirm_invoice(inv)
    if inv.status == "cancelled":
        raise HTTPException(400, "Cancelled invoices cannot be sent")
    customer: User = inv.customer
    body = (f"Hello {customer.name},\n\nInvoice {inv.invoice_number} for subscription "
            f"{inv.subscription.subscription_number} covering {inv.period_start} to {inv.period_end}.\n\n"
            f"Subtotal: {inv.subtotal:,.2f}\nDiscount: -{inv.discount_amount:,.2f}\nTax: {inv.tax_amount:,.2f}\n"
            f"Total: {inv.total_amount:,.2f}\nBalance due: {inv.balance_due:,.2f} by {inv.due_date}\n\n"
            "You can view and pay it in your Brightloop customer portal.\n\nBrightloop Software")
    send_email(db, customer.email, f"Invoice {inv.invoice_number} from Brightloop Software", body)
    inv.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
    blackbox.record(inv.subscription, "invoice_sent", f"Invoice {inv.invoice_number} emailed to {customer.email}",
                    data={"invoice": inv.invoice_number, "to": customer.email})
    return inv
