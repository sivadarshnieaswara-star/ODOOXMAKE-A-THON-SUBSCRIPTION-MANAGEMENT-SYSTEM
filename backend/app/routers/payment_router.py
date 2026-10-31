from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Payment, Invoice, User, UserRole
from ..schemas import PaymentCreate, PaymentResponse
from ..auth import get_current_user, require_staff_or_admin
from ..services.payment_service import PaymentService

router = APIRouter(prefix="/api/payments", tags=["Payments & Collections"])

@router.get("", response_model=List[PaymentResponse])
def list_payments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists payments. Customers see only their own payments; Staff and Admin see all."""
    query = db.query(Payment)
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Payment.customer_id == current_user.id)

    payments = query.order_by(Payment.id.desc()).all()
    results = []
    for p in payments:
        inv = db.query(Invoice).filter(Invoice.id == p.invoice_id).first()
        results.append(PaymentResponse(
            id=p.id,
            payment_number=p.payment_number,
            invoice_id=p.invoice_id,
            invoice_number=inv.invoice_number if inv else "INV-N/A",
            customer_id=p.customer_id,
            customer_name=p.customer.name if p.customer else None,
            amount=p.amount,
            payment_method=p.payment_method,
            payment_date=p.payment_date,
            note=p.note,
            created_at=p.created_at
        ))
    return results

@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def record_payment(
    payment_in: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Records a payment against an invoice and automatically reconciles balance due.
    Customers can pay their own invoices; Staff and Admin can record on behalf.
    """
    invoice = db.query(Invoice).filter(Invoice.id == payment_in.invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    if current_user.role == UserRole.CUSTOMER and invoice.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only pay for your own invoices.")

    payment, updated_invoice = PaymentService.record_payment(
        db=db,
        invoice_id=payment_in.invoice_id,
        amount=payment_in.amount,
        payment_method=payment_in.payment_method,
        payment_date=payment_in.payment_date,
        note=payment_in.note,
        customer_id=invoice.customer_id
    )

    return PaymentResponse(
        id=payment.id,
        payment_number=payment.payment_number,
        invoice_id=payment.invoice_id,
        invoice_number=updated_invoice.invoice_number,
        customer_id=payment.customer_id,
        customer_name=payment.customer.name if payment.customer else None,
        amount=payment.amount,
        payment_method=payment.payment_method,
        payment_date=payment.payment_date,
        note=payment.note,
        created_at=payment.created_at
    )

@router.get("/overdue")
def get_overdue_invoices(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin)
):
    """Returns list of all overdue invoices past their due date with aging analysis."""
    return PaymentService.get_overdue_invoices(db)
