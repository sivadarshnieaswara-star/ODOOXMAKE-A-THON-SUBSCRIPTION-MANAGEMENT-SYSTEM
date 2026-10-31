from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session
from ..models import (
    Subscription, SubscriptionStatus, Invoice, InvoiceLine, InvoiceStatus,
    BillingFrequency, TaxRule
)
from .discount_service import DiscountService
from .tax_service import TaxService

class BillingService:
    @staticmethod
    def calculate_next_billing_date(current_date: date, frequency: str) -> date:
        """Calculates next billing date based on plan frequency."""
        freq = frequency.lower()
        if freq == BillingFrequency.DAILY:
            return current_date + timedelta(days=1)
        elif freq == BillingFrequency.WEEKLY:
            return current_date + timedelta(days=7)
        elif freq == BillingFrequency.MONTHLY:
            return current_date + relativedelta(months=1)
        elif freq == BillingFrequency.YEARLY:
            return current_date + relativedelta(years=1)
        return current_date + relativedelta(months=1)

    @staticmethod
    def generate_invoice_number(db: Session) -> str:
        """Generates next sequential invoice number like INV-00001."""
        count = db.query(Invoice).count() + 1
        return f"INV-{count:05d}"

    @classmethod
    def generate_invoice_for_subscription(
        cls,
        db: Session,
        subscription: Subscription,
        billing_date: Optional[date] = None,
        force: bool = False
    ) -> Tuple[Optional[Invoice], str]:
        """
        Creates an invoice from a subscription.
        Idempotent: prevents double-billing for the same billing date.
        """
        if subscription.status != SubscriptionStatus.ACTIVE:
            return None, f"Subscription {subscription.subscription_number} is not active (status: {subscription.status})."

        today = billing_date or date.today()

        # Idempotency check: verify an invoice has not already been created for this billing period
        if not force and subscription.last_billing_date == today:
            return None, f"Subscription {subscription.subscription_number} has already been billed for {today}."

        # Double check existing invoice for the exact date and subscription
        existing_invoice = db.query(Invoice).filter(
            Invoice.subscription_id == subscription.id,
            Invoice.issue_date == today,
            Invoice.status != InvoiceStatus.CANCELLED
        ).first()
        if existing_invoice and not force:
            return existing_invoice, f"Invoice {existing_invoice.invoice_number} already exists for this billing period."

        # Compute line totals and tax
        subtotal = 0.0
        total_quantity = 0
        invoice_lines = []

        default_tax_rate = TaxService.get_default_tax_rate(db)

        for line in subscription.lines:
            product_name = line.product.name if line.product else "Service Item"
            variant_name = (
                f"{line.variant.attribute_name}: {line.variant.variant_value}"
                if line.variant else None
            )
            line_subtotal = round(line.quantity * line.unit_price, 2)
            subtotal += line_subtotal
            total_quantity += line.quantity

            tax_rate = line.tax_rate if line.tax_rate > 0 else default_tax_rate
            line_tax = TaxService.compute_tax(line_subtotal, tax_rate)
            line_total = round(line_subtotal + line_tax, 2)

            invoice_lines.append(InvoiceLine(
                product_name=product_name,
                variant_name=variant_name,
                quantity=line.quantity,
                unit_price=line.unit_price,
                tax_rate=tax_rate,
                line_subtotal=line_subtotal,
                line_tax=line_tax,
                line_total=line_total
            ))

        subtotal = round(subtotal, 2)

        # Evaluate automated discount rules
        best_rule, discount_amount = DiscountService.evaluate_best_discount(
            db=db,
            subscription=subscription,
            subtotal=subtotal,
            total_quantity=total_quantity,
            evaluation_date=today
        )

        taxable_subtotal = max(0.0, subtotal - discount_amount)
        # Recalculate taxes proportional to discounted subtotal
        total_tax = 0.0
        for inv_line in invoice_lines:
            if subtotal > 0:
                line_discount = (inv_line.line_subtotal / subtotal) * discount_amount
                line_taxable = max(0.0, inv_line.line_subtotal - line_discount)
            else:
                line_taxable = inv_line.line_subtotal
            inv_line.line_tax = TaxService.compute_tax(line_taxable, inv_line.tax_rate)
            inv_line.line_total = round(line_taxable + inv_line.line_tax, 2)
            total_tax += inv_line.line_tax

        total_tax = round(total_tax, 2)
        total_amount = round(taxable_subtotal + total_tax, 2)

        # Payment terms due date
        due_days = 15
        if subscription.payment_terms:
            if "30" in subscription.payment_terms:
                due_days = 30
            elif "7" in subscription.payment_terms:
                due_days = 7
            elif "immediate" in subscription.payment_terms.lower():
                due_days = 0

        due_date = today + timedelta(days=due_days)

        invoice_number = cls.generate_invoice_number(db)

        invoice = Invoice(
            invoice_number=invoice_number,
            subscription_id=subscription.id,
            customer_id=subscription.customer_id,
            issue_date=today,
            due_date=due_date,
            status=InvoiceStatus.DRAFT,
            subtotal=subtotal,
            discount_amount=discount_amount,
            discount_code=best_rule.code if best_rule else None,
            tax_amount=total_tax,
            total_amount=total_amount,
            balance_due=total_amount,
            notes=f"Recurring billing for plan '{subscription.plan.name if subscription.plan else 'Subscription'}'",
            lines=invoice_lines
        )

        db.add(invoice)

        # Consume discount usage
        if best_rule:
            DiscountService.consume_discount(db, best_rule)

        # Advance subscription billing cycle
        subscription.last_billing_date = today
        freq = subscription.plan.billing_frequency if subscription.plan else BillingFrequency.MONTHLY
        subscription.next_billing_date = cls.calculate_next_billing_date(today, freq)

        db.commit()
        db.refresh(invoice)
        return invoice, f"Successfully created invoice {invoice_number}."

    @classmethod
    def run_bulk_recurring_billing(cls, db: Session, target_date: Optional[date] = None) -> dict:
        """
        Executes billing day batch run for all due active subscriptions.
        Returns detailed summary.
        """
        today = target_date or date.today()
        # Find active subscriptions due on or before today
        due_subscriptions = db.query(Subscription).filter(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.next_billing_date <= today
        ).all()

        invoices_created = []
        skipped = []

        for sub in due_subscriptions:
            # Check if subscription reached expiry and has auto_close policy
            if sub.expiry_date and sub.expiry_date < today:
                if sub.plan and sub.plan.auto_close_on_expiry:
                    sub.status = SubscriptionStatus.CLOSED
                    db.commit()
                    skipped.append({
                        "subscription_number": sub.subscription_number,
                        "reason": f"Subscription expired on {sub.expiry_date} and auto-closed."
                    })
                    continue

            inv, msg = cls.generate_invoice_for_subscription(db, sub, billing_date=today)
            if inv:
                invoices_created.append({
                    "subscription_number": sub.subscription_number,
                    "invoice_number": inv.invoice_number,
                    "total_amount": inv.total_amount,
                    "customer_id": inv.customer_id
                })
            else:
                skipped.append({
                    "subscription_number": sub.subscription_number,
                    "reason": msg
                })

        return {
            "execution_date": str(today),
            "total_due_found": len(due_subscriptions),
            "invoices_generated_count": len(invoices_created),
            "skipped_count": len(skipped),
            "invoices": invoices_created,
            "skipped": skipped
        }
