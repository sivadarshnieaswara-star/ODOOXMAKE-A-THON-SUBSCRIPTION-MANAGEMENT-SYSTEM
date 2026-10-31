from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Invoice, InvoiceStatus, User, UserRole
from ..schemas import InvoiceResponse, InvoiceLineResponse, InvoiceStatusUpdate
from ..auth import get_current_user, require_staff_or_admin
from ..services.billing_service import BillingService
from ..config import COMPANY_NAME, COMPANY_EMAIL, COMPANY_PHONE, COMPANY_ADDRESS

router = APIRouter(prefix="/api/invoices", tags=["Invoices & Billing"])

def build_invoice_response(inv: Invoice) -> InvoiceResponse:
    lines = [
        InvoiceLineResponse(
            id=l.id,
            product_name=l.product_name,
            variant_name=l.variant_name,
            quantity=l.quantity,
            unit_price=l.unit_price,
            tax_rate=l.tax_rate,
            line_subtotal=l.line_subtotal,
            line_tax=l.line_tax,
            line_total=l.line_total
        )
        for l in inv.lines
    ]
    is_overdue = inv.status == InvoiceStatus.CONFIRMED and inv.balance_due > 0 and inv.due_date < date.today()
    return InvoiceResponse(
        id=inv.id,
        invoice_number=inv.invoice_number,
        subscription_id=inv.subscription_id,
        customer_id=inv.customer_id,
        customer_name=inv.customer.name if inv.customer else None,
        customer_email=inv.customer.email if inv.customer else None,
        issue_date=inv.issue_date,
        due_date=inv.due_date,
        status=inv.status,
        subtotal=inv.subtotal,
        discount_amount=inv.discount_amount,
        discount_code=inv.discount_code,
        tax_amount=inv.tax_amount,
        total_amount=inv.total_amount,
        balance_due=inv.balance_due,
        is_overdue=is_overdue,
        sent_at=inv.sent_at,
        notes=inv.notes,
        lines=lines,
        created_at=inv.created_at
    )

@router.get("", response_model=List[InvoiceResponse])
def list_invoices(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists invoices. Customers see only their own invoices; Staff and Admin see all."""
    query = db.query(Invoice)
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Invoice.customer_id == current_user.id)
    if status_filter:
        query = query.filter(Invoice.status == status_filter.lower())

    invoices = query.order_by(Invoice.id.desc()).all()
    return [build_invoice_response(inv) for inv in invoices]

@router.get("/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves invoice details."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if current_user.role == UserRole.CUSTOMER and inv.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access forbidden.")
    return build_invoice_response(inv)

@router.post("/{invoice_id}/status", response_model=InvoiceResponse)
def update_invoice_status(
    invoice_id: int,
    status_update: InvoiceStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin)
):
    """Transitions invoice state: draft -> confirmed -> cancelled."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    target = status_update.status.lower()
    if target not in [InvoiceStatus.CONFIRMED, InvoiceStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail="Allowed status transitions: confirmed, cancelled.")

    inv.status = target
    db.commit()
    db.refresh(inv)
    return build_invoice_response(inv)

@router.post("/run-recurring")
def run_recurring_billing_batch(
    target_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin)
):
    """
    Executes bulk recurring billing run for all active subscriptions due today.
    Idempotent: prevents duplicate invoices or skipped subscriptions.
    """
    summary = BillingService.run_bulk_recurring_billing(db, target_date=target_date)
    return summary

@router.get("/{invoice_id}/print", response_class=HTMLResponse)
def print_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns clean, printable HTML invoice with Brightloop branding."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if current_user.role == UserRole.CUSTOMER and inv.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access forbidden.")

    # Render clean printable invoice
    rows_html = "".join([
        f"""<tr>
            <td style="padding:10px;border-bottom:1px solid #e5e7eb;">
                <strong>{l.product_name}</strong>
                {f'<br><small style="color:#6b7280;">{l.variant_name}</small>' if l.variant_name else ''}
            </td>
            <td style="padding:10px;border-bottom:1px solid #e5e7eb;text-align:center;">{l.quantity}</td>
            <td style="padding:10px;border-bottom:1px solid #e5e7eb;text-align:right;">${l.unit_price:.2f}</td>
            <td style="padding:10px;border-bottom:1px solid #e5e7eb;text-align:right;">${l.line_total:.2f}</td>
        </tr>""" for l in inv.lines
    ])

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Invoice {inv.invoice_number} - {COMPANY_NAME}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; color: #1f2937; margin: 40px; }}
        .header {{ display: flex; justify-content: space-between; border-bottom: 3px solid #714B67; padding-bottom: 20px; }}
        .logo {{ font-size: 28px; font-weight: bold; color: #714B67; }}
        .badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; text-transform: uppercase; font-size: 12px; }}
        .badge-paid {{ background: #d1fae5; color: #065f46; }}
        .badge-confirmed {{ background: #dbeafe; color: #1e40af; }}
        .badge-draft {{ background: #f3f4f6; color: #4b5563; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 30px; }}
        th {{ background: #714B67; color: white; padding: 12px 10px; text-align: left; }}
        .totals {{ float: right; width: 300px; margin-top: 20px; }}
        .totals tr td {{ padding: 6px 0; }}
        .print-btn {{ background: #714B67; color: white; padding: 10px 18px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; margin-bottom: 20px; }}
        @media print {{ .print-btn {{ display: none; }} body {{ margin: 0; }} }}
    </style>
</head>
<body>
    <button class="print-btn" onclick="window.print()">🖨️ Print / Save as PDF</button>
    <div class="header">
        <div>
            <div class="logo">{COMPANY_NAME}</div>
            <div style="color: #6b7280; font-size: 13px; margin-top: 5px;">
                {COMPANY_ADDRESS}<br>
                {COMPANY_EMAIL} | {COMPANY_PHONE}
            </div>
        </div>
        <div style="text-align: right;">
            <h2 style="margin: 0; color: #1f2937;">INVOICE</h2>
            <div style="font-size: 16px; font-weight: bold; color: #714B67; margin-top: 4px;">{inv.invoice_number}</div>
            <div style="margin-top: 6px;">
                <span class="badge badge-{inv.status}">Status: {inv.status}</span>
            </div>
        </div>
    </div>

    <div style="display: flex; justify-content: space-between; margin-top: 30px;">
        <div>
            <div style="font-size: 12px; color: #6b7280; font-weight: bold; text-transform: uppercase;">Billed To:</div>
            <div style="font-size: 16px; font-weight: bold; margin-top: 4px;">{inv.customer.name if inv.customer else 'Valued Customer'}</div>
            <div style="color: #4b5563;">{inv.customer.email if inv.customer else ''}</div>
            {f'<div style="color:#6b7280;">{inv.customer.company_name}</div>' if inv.customer and inv.customer.company_name else ''}
        </div>
        <div style="text-align: right;">
            <div style="color: #4b5563;"><strong>Issue Date:</strong> {inv.issue_date}</div>
            <div style="color: #4b5563; margin-top: 4px;"><strong>Due Date:</strong> {inv.due_date}</div>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Description</th>
                <th style="text-align: center;">Qty</th>
                <th style="text-align: right;">Unit Price</th>
                <th style="text-align: right;">Total</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    <table class="totals">
        <tr>
            <td>Subtotal:</td>
            <td style="text-align: right;"><strong>${inv.subtotal:.2f}</strong></td>
        </tr>
        {f'<tr><td style="color:#059669;">Discount ({inv.discount_code or "Applied"}):</td><td style="text-align:right;color:#059669;"><strong>-${inv.discount_amount:.2f}</strong></td></tr>' if inv.discount_amount > 0 else ''}
        <tr>
            <td>Tax:</td>
            <td style="text-align: right;">${inv.tax_amount:.2f}</td>
        </tr>
        <tr style="border-top: 2px solid #714B67; font-size: 16px;">
            <td><strong>Total:</strong></td>
            <td style="text-align: right;"><strong>${inv.total_amount:.2f}</strong></td>
        </tr>
        <tr style="color: {'#dc2626' if inv.balance_due > 0 else '#059669'}; font-size: 15px;">
            <td><strong>Balance Due:</strong></td>
            <td style="text-align: right;"><strong>${inv.balance_due:.2f}</strong></td>
        </tr>
    </table>
</body>
</html>"""
    return HTMLResponse(content=html)
