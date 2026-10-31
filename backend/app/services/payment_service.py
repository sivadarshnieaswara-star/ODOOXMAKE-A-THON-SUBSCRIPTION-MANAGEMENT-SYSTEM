from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Invoice, Payment, User
from .common import next_number


def record_payment(db: Session, inv: Invoice, amount: float, method: str, payment_date: date | None,
                   note: str | None, actor: User) -> Payment:
    """Apply a payment to an invoice; the invoice flips to Paid once nothing is owed."""
    if inv.status != "confirmed":
        raise HTTPException(400, f"Payments can only be recorded on confirmed invoices (this one is {inv.status})")
    amount = round(amount, 2)
    if amount > round(inv.balance_due, 2) + 0.001:
        raise HTTPException(400, f"Payment {amount:,.2f} exceeds the balance due {inv.balance_due:,.2f}")
    paid_on = payment_date or date.today()
    pay = Payment(payment_number=next_number(db, "payment"), invoice=inv, customer_id=inv.customer_id,
                  amount=amount, payment_method=method, payment_date=paid_on, note=note,
                  recorded_by=actor.email)
    db.add(pay)
    inv.balance_due = round(inv.balance_due - amount, 2)
    if inv.balance_due <= 0.001:
        inv.balance_due = 0.0
        inv.status = "paid"
        inv.paid_at = paid_on
    db.flush()
    return pay
