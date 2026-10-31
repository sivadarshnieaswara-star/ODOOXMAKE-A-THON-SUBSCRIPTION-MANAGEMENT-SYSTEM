from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import TaxRule, User
from ..schemas import TaxRuleCreate, TaxRuleUpdate, TaxRuleResponse
from ..auth import get_current_user, require_admin

router = APIRouter(prefix="/api/taxes", tags=["Tax Rules"])

@router.get("", response_model=List[TaxRuleResponse])
def list_tax_rules(
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists tax rules."""
    query = db.query(TaxRule)
    if active_only:
        query = query.filter(TaxRule.is_active == True)
    return [TaxRuleResponse.model_validate(t) for t in query.all()]

@router.get("/{tax_id}", response_model=TaxRuleResponse)
def get_tax_rule(
    tax_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves a single tax rule."""
    tax = db.query(TaxRule).filter(TaxRule.id == tax_id).first()
    if not tax:
        raise HTTPException(status_code=404, detail="Tax rule not found.")
    return TaxRuleResponse.model_validate(tax)

@router.post("", response_model=TaxRuleResponse, status_code=status.HTTP_201_CREATED)
def create_tax_rule(
    tax_in: TaxRuleCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    """Creates a new tax rule. Restricted strictly to Admin."""
    if tax_in.rate_percentage < 0:
        raise HTTPException(status_code=400, detail="Tax rate percentage cannot be negative.")

    if tax_in.is_default:
        # Clear existing defaults
        db.query(TaxRule).update({TaxRule.is_default: False})

    tax = TaxRule(
        name=tax_in.name,
        rate_percentage=tax_in.rate_percentage,
        is_default=tax_in.is_default,
        is_active=True
    )
    db.add(tax)
    db.commit()
    db.refresh(tax)
    return TaxRuleResponse.model_validate(tax)

@router.put("/{tax_id}", response_model=TaxRuleResponse)
def update_tax_rule(
    tax_id: int,
    tax_in: TaxRuleUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    """Updates a tax rule. Restricted strictly to Admin."""
    tax = db.query(TaxRule).filter(TaxRule.id == tax_id).first()
    if not tax:
        raise HTTPException(status_code=404, detail="Tax rule not found.")

    if tax_in.name is not None:
        tax.name = tax_in.name
    if tax_in.rate_percentage is not None:
        if tax_in.rate_percentage < 0:
            raise HTTPException(status_code=400, detail="Tax rate percentage cannot be negative.")
        tax.rate_percentage = tax_in.rate_percentage
    if tax_in.is_default is not None:
        if tax_in.is_default:
            db.query(TaxRule).filter(TaxRule.id != tax.id).update({TaxRule.is_default: False})
        tax.is_default = tax_in.is_default
    if tax_in.is_active is not None:
        tax.is_active = tax_in.is_active

    db.commit()
    db.refresh(tax)
    return TaxRuleResponse.model_validate(tax)

@router.delete("/{tax_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tax_rule(
    tax_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    """Deletes or soft-deactivates a tax rule. Restricted to Admin."""
    tax = db.query(TaxRule).filter(TaxRule.id == tax_id).first()
    if not tax:
        raise HTTPException(status_code=404, detail="Tax rule not found.")
    db.delete(tax)
    db.commit()
    return None
