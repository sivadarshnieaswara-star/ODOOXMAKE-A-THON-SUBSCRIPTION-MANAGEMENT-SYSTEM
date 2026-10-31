from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import DiscountRule, DiscountType, DiscountTarget, Product, User
from ..schemas import DiscountRuleCreate, DiscountRuleUpdate, DiscountRuleResponse
from ..auth import get_current_user, require_admin

router = APIRouter(prefix="/api/discounts", tags=["Discount Rules"])

@router.get("", response_model=List[DiscountRuleResponse])
def list_discount_rules(
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists configured discount rules."""
    query = db.query(DiscountRule)
    if active_only:
        query = query.filter(DiscountRule.is_active == True)
    return [DiscountRuleResponse.model_validate(d) for d in query.order_by(DiscountRule.id.desc()).all()]

@router.get("/{discount_id}", response_model=DiscountRuleResponse)
def get_discount_rule(
    discount_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves single discount rule details."""
    rule = db.query(DiscountRule).filter(DiscountRule.id == discount_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Discount rule not found.")
    return DiscountRuleResponse.model_validate(rule)

@router.post("", response_model=DiscountRuleResponse, status_code=status.HTTP_201_CREATED)
def create_discount_rule(
    rule_in: DiscountRuleCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    """Creates a new discount rule. Restricted strictly to Admin."""
    existing = db.query(DiscountRule).filter(DiscountRule.code == rule_in.code.upper()).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Discount rule code '{rule_in.code}' already exists.")

    if rule_in.discount_type not in [DiscountType.PERCENTAGE, DiscountType.FIXED]:
        raise HTTPException(status_code=400, detail="Invalid discount_type. Allowed: percentage, fixed.")

    if rule_in.discount_type == DiscountType.PERCENTAGE and (rule_in.value <= 0 or rule_in.value > 100):
        raise HTTPException(status_code=400, detail="Percentage discount must be between 0 and 100.")

    if rule_in.value <= 0:
        raise HTTPException(status_code=400, detail="Discount value must be greater than zero.")

    if rule_in.target_type not in [DiscountTarget.SUBSCRIPTION, DiscountTarget.PRODUCT]:
        raise HTTPException(status_code=400, detail="Invalid target_type. Allowed: subscription, product.")

    if rule_in.target_type == DiscountTarget.PRODUCT:
        if not rule_in.product_id:
            raise HTTPException(status_code=400, detail="product_id is required when target_type is 'product'.")
        prod = db.query(Product).filter(Product.id == rule_in.product_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail="Target product not found.")

    rule = DiscountRule(
        code=rule_in.code.upper(),
        description=rule_in.description,
        discount_type=rule_in.discount_type,
        value=rule_in.value,
        min_purchase=rule_in.min_purchase,
        min_quantity=rule_in.min_quantity,
        start_date=rule_in.start_date,
        end_date=rule_in.end_date,
        max_uses=rule_in.max_uses,
        current_uses=0,
        target_type=rule_in.target_type,
        product_id=rule_in.product_id,
        is_active=True
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return DiscountRuleResponse.model_validate(rule)

@router.put("/{discount_id}", response_model=DiscountRuleResponse)
def update_discount_rule(
    discount_id: int,
    rule_in: DiscountRuleUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    """Updates a discount rule. Restricted strictly to Admin."""
    rule = db.query(DiscountRule).filter(DiscountRule.id == discount_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Discount rule not found.")

    if rule_in.code is not None:
        conflict = db.query(DiscountRule).filter(
            DiscountRule.code == rule_in.code.upper(),
            DiscountRule.id != rule.id
        ).first()
        if conflict:
            raise HTTPException(status_code=400, detail=f"Discount code '{rule_in.code}' is already used.")
        rule.code = rule_in.code.upper()

    if rule_in.description is not None:
        rule.description = rule_in.description
    if rule_in.discount_type is not None:
        if rule_in.discount_type not in [DiscountType.PERCENTAGE, DiscountType.FIXED]:
            raise HTTPException(status_code=400, detail="Invalid discount_type.")
        rule.discount_type = rule_in.discount_type
    if rule_in.value is not None:
        if rule_in.value <= 0:
            raise HTTPException(status_code=400, detail="Discount value must be greater than zero.")
        rule.value = rule_in.value
    if rule_in.min_purchase is not None:
        rule.min_purchase = rule_in.min_purchase
    if rule_in.min_quantity is not None:
        rule.min_quantity = rule_in.min_quantity
    if rule_in.start_date is not None:
        rule.start_date = rule_in.start_date
    if rule_in.end_date is not None:
        rule.end_date = rule_in.end_date
    if rule_in.max_uses is not None:
        rule.max_uses = rule_in.max_uses
    if rule_in.target_type is not None:
        rule.target_type = rule_in.target_type
    if rule_in.product_id is not None:
        rule.product_id = rule_in.product_id
    if rule_in.is_active is not None:
        rule.is_active = rule_in.is_active

    db.commit()
    db.refresh(rule)
    return DiscountRuleResponse.model_validate(rule)

@router.delete("/{discount_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_discount_rule(
    discount_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    """Deletes a discount rule. Restricted strictly to Admin."""
    rule = db.query(DiscountRule).filter(DiscountRule.id == discount_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Discount rule not found.")
    db.delete(rule)
    db.commit()
    return None
