from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import QuotationTemplate, QuotationTemplateLine, Plan, Product, ProductVariant, User, UserRole
from ..schemas import (
    TemplateCreate, TemplateUpdate, TemplateResponse, TemplateLineResponse,
    TemplateInstantiateRequest, SubscriptionResponse
)
from ..auth import get_current_user, require_staff_or_admin
from ..services.subscription_service import SubscriptionService
from .subscription_router import build_subscription_response

router = APIRouter(prefix="/api/templates", tags=["Quotation Templates"])

def build_template_response(template: QuotationTemplate) -> TemplateResponse:
    lines = []
    for l in template.lines:
        prod_name = l.product.name if l.product else None
        var_name = f"{l.variant.attribute_name}: {l.variant.variant_value}" if l.variant else None
        lines.append(TemplateLineResponse(
            id=l.id,
            product_id=l.product_id,
            product_name=prod_name,
            variant_id=l.variant_id,
            variant_name=var_name,
            quantity=l.quantity,
            unit_price=l.unit_price
        ))
    return TemplateResponse(
        id=template.id,
        name=template.name,
        validity_days=template.validity_days,
        plan_id=template.plan_id,
        plan_name=template.plan.name if template.plan else None,
        notes=template.notes,
        lines=lines
    )

@router.get("", response_model=List[TemplateResponse])
def list_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists all quotation templates."""
    templates = db.query(QuotationTemplate).order_by(QuotationTemplate.id.desc()).all()
    return [build_template_response(t) for t in templates]

@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves a quotation template by ID."""
    template = db.query(QuotationTemplate).filter(QuotationTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Quotation template not found.")
    return build_template_response(template)

@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(
    template_in: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin)
):
    """Creates a new quotation template with configured line items."""
    if template_in.plan_id:
        plan = db.query(Plan).filter(Plan.id == template_in.plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Selected plan not found.")

    template = QuotationTemplate(
        name=template_in.name,
        validity_days=template_in.validity_days,
        plan_id=template_in.plan_id,
        notes=template_in.notes
    )
    db.add(template)
    db.flush()

    for l_in in template_in.lines:
        prod = db.query(Product).filter(Product.id == l_in.product_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail=f"Product with id {l_in.product_id} not found.")

        if l_in.variant_id:
            var = db.query(ProductVariant).filter(
                ProductVariant.id == l_in.variant_id,
                ProductVariant.product_id == l_in.product_id
            ).first()
            if not var:
                raise HTTPException(status_code=404, detail=f"Variant with id {l_in.variant_id} does not match product {l_in.product_id}.")

        line = QuotationTemplateLine(
            template_id=template.id,
            product_id=l_in.product_id,
            variant_id=l_in.variant_id,
            quantity=l_in.quantity,
            unit_price=l_in.unit_price
        )
        db.add(line)

    db.commit()
    db.refresh(template)
    return build_template_response(template)

@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(
    template_id: int,
    update_in: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin)
):
    """Updates quotation template details and optional lines."""
    template = db.query(QuotationTemplate).filter(QuotationTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Quotation template not found.")

    if update_in.name is not None:
        template.name = update_in.name
    if update_in.validity_days is not None:
        template.validity_days = update_in.validity_days
    if update_in.plan_id is not None:
        plan = db.query(Plan).filter(Plan.id == update_in.plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found.")
        template.plan_id = update_in.plan_id
    if update_in.notes is not None:
        template.notes = update_in.notes

    if update_in.lines is not None:
        # Replace line items
        db.query(QuotationTemplateLine).filter(QuotationTemplateLine.template_id == template.id).delete()
        for l_in in update_in.lines:
            line = QuotationTemplateLine(
                template_id=template.id,
                product_id=l_in.product_id,
                variant_id=l_in.variant_id,
                quantity=l_in.quantity,
                unit_price=l_in.unit_price
            )
            db.add(line)

    db.commit()
    db.refresh(template)
    return build_template_response(template)

@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin)
):
    """Deletes a quotation template."""
    template = db.query(QuotationTemplate).filter(QuotationTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Quotation template not found.")
    db.delete(template)
    db.commit()
    return None

@router.post("/{template_id}/instantiate", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
def instantiate_subscription_from_template(
    template_id: int,
    req: TemplateInstantiateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Instantiates a new subscription quotation directly from a predefined Quotation Template.
    If called by Customer, uses their customer ID.
    If called by Staff/Admin, can specify customer_id or default to caller.
    """
    if current_user.role == UserRole.CUSTOMER:
        target_customer_id = current_user.id
    else:
        target_customer_id = req.customer_id or current_user.id

    customer = db.query(User).filter(User.id == target_customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found.")

    sub = SubscriptionService.create_from_template(
        db=db,
        customer_id=target_customer_id,
        template_id=template_id,
        start_date=req.start_date,
        payment_terms=req.payment_terms
    )
    return build_subscription_response(sub)
