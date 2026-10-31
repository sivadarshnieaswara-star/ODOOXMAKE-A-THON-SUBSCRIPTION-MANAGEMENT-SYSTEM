"""Invoices, billing runs, payments and finance analytics."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user, require_customer, require_staff
from ..config import FRONTEND_DIR
from ..database import get_db
from ..models import Invoice, Payment, User
from ..schemas import BillingRunIn, BillingRunOut, InvoiceOut, PaymentIn, PaymentOut, PortalPayIn
from ..serializers import invoice_out, payment_out
from ..services import analytics_service, billing_service, payment_service

router = APIRouter(prefix="/api", tags=["billing"])

_jinja = Environment(loader=FileSystemLoader(FRONTEND_DIR / "templates"), autoescape=select_autoescape())


def load_invoice(db: Session, inv_id: int, user: User) -> Invoice:
    inv = db.get(Invoice, inv_id)
    # Customers see their own invoices once they have been issued (not internal drafts).
    if inv is None or (user.role == "customer" and (inv.customer_id != user.id or inv.status == "draft")):
        raise HTTPException(404, "Invoice not found")
    return inv


# ---------- Invoices ----------
@router.get("/invoices")
def list_invoices(status: str | None = None, overdue: bool = False, customer_id: int | None = None,
                  subscription_id: int | None = None, q: str | None = None, limit: int = 50, offset: int = 0,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    filters = []
    if user.role == "customer":
        filters += [Invoice.customer_id == user.id, Invoice.status != "draft"]
    elif customer_id:
        filters.append(Invoice.customer_id == customer_id)
    if subscription_id:
        filters.append(Invoice.subscription_id == subscription_id)
    if status == "outstanding":
        filters += [Invoice.status == "confirmed", Invoice.balance_due > 0]
    elif status:
        filters.append(Invoice.status == status)
    if overdue:
        filters += [Invoice.status == "confirmed", Invoice.balance_due > 0, Invoice.due_date < today]
    if q:
        like = f"%{q.lower()}%"
        filters.append(or_(func.lower(Invoice.invoice_number).like(like),
                           Invoice.customer_id.in_(select(User.id).where(or_(
                               func.lower(User.name).like(like), func.lower(User.company_name).like(like))))))
    total = db.scalar(select(func.count()).select_from(Invoice).where(*filters))
    invs = db.scalars(
        select(Invoice).where(*filters)
        .options(selectinload(Invoice.customer), selectinload(Invoice.subscription))
        .order_by(Invoice.id.desc()).limit(min(limit, 500)).offset(offset)).all()
    return {"total": total, "items": [invoice_out(i, detail=False, today=today) for i in invs]}


@router.get("/invoices/{inv_id}", response_model=InvoiceOut)
def get_invoice(inv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return invoice_out(load_invoice(db, inv_id, user))


@router.post("/billing/run", response_model=BillingRunOut)
def billing_run(data: BillingRunIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Billing day: invoice every subscription that is due. Safe to run any number of times."""
    return billing_service.run_billing(db, data.as_of, data.auto_confirm)


@router.post("/invoices/{inv_id}/{action}", response_model=InvoiceOut)
def invoice_action(inv_id: int, action: str, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    inv = load_invoice(db, inv_id, user)
    if action == "confirm":
        billing_service.confirm_invoice(inv)
    elif action == "cancel":
        billing_service.cancel_invoice(db, inv)
    elif action == "send":
        billing_service.send_invoice(db, inv)
    else:
        raise HTTPException(400, f"Unknown invoice action '{action}'")
    db.commit()
    return invoice_out(inv)


@router.get("/invoices/{inv_id}/print", response_class=HTMLResponse)
def print_invoice(inv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inv = load_invoice(db, inv_id, user)
    return _jinja.get_template("invoice_print.html").render(inv=invoice_out(inv), today=date.today())


# ---------- Payments ----------
@router.get("/payments")
def list_payments(customer_id: int | None = None, method: str | None = None, date_from: date | None = None,
                  date_to: date | None = None, limit: int = 50, offset: int = 0,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    filters = []
    if user.role == "customer":
        filters.append(Payment.customer_id == user.id)
    elif customer_id:
        filters.append(Payment.customer_id == customer_id)
    if method:
        filters.append(Payment.payment_method == method)
    if date_from:
        filters.append(Payment.payment_date >= date_from)
    if date_to:
        filters.append(Payment.payment_date <= date_to)
    total = db.scalar(select(func.count()).select_from(Payment).where(*filters))
    pays = db.scalars(
        select(Payment).where(*filters)
        .options(selectinload(Payment.invoice), selectinload(Payment.customer))
        .order_by(Payment.id.desc()).limit(min(limit, 500)).offset(offset)).all()
    return {"total": total, "items": [payment_out(p) for p in pays]}


@router.post("/payments", response_model=PaymentOut, status_code=201)
def create_payment(data: PaymentIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    inv = load_invoice(db, data.invoice_id, user)
    pay = payment_service.record_payment(db, inv, data.amount, data.payment_method, data.payment_date,
                                         data.note, user)
    db.commit()
    return payment_out(pay)


@router.post("/portal/invoices/{inv_id}/pay", response_model=PaymentOut, status_code=201)
def portal_pay(inv_id: int, data: PortalPayIn, user: User = Depends(require_customer),
               db: Session = Depends(get_db)):
    """Customer pays the full balance of their own invoice (payment gateway simulated)."""
    inv = load_invoice(db, inv_id, user)
    pay = payment_service.record_payment(db, inv, inv.balance_due, data.payment_method, None,
                                         "Paid online via customer portal", user)
    db.commit()
    return payment_out(pay)


# ---------- Finance analytics ----------
@router.get("/analytics/summary")
def analytics_summary(date_from: date | None = None, date_to: date | None = None, plan_id: int | None = None,
                      customer_id: int | None = None, user: User = Depends(require_staff),
                      db: Session = Depends(get_db)):
    return analytics_service.summary(db, date_from=date_from, date_to=date_to, plan_id=plan_id,
                                     customer_id=customer_id)


@router.get("/analytics/overdue")
def analytics_overdue(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return analytics_service.overdue_invoices(db)
