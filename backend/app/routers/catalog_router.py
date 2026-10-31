"""Plans, tax rules and discount rules: configured by the admin, readable by the team."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin, require_staff
from ..database import get_db
from ..models import DiscountRule, Plan, Product, Subscription, TaxRule, User
from ..schemas import DiscountIn, DiscountOut, PlanIn, PlanOut, TaxIn, TaxOut
from ..services.tax_service import set_default

router = APIRouter(prefix="/api", tags=["catalog"])


def _get(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{label} not found")
    return obj


# ---------- Plans ----------
def _check_plan(data: PlanIn):
    if data.start_date and data.end_date and data.end_date < data.start_date:
        raise HTTPException(400, "Plan end date must be on or after its start date")


@router.get("/plans", response_model=list[PlanOut])
def list_plans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Plan).order_by(Plan.name)
    if user.role == "customer":
        stmt = stmt.where(Plan.is_active.is_(True))
    return db.scalars(stmt).all()


@router.post("/plans", response_model=PlanOut, status_code=201)
def create_plan(data: PlanIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _check_plan(data)
    plan = Plan(**data.model_dump())
    db.add(plan)
    db.commit()
    return plan


@router.put("/plans/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, data: PlanIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _check_plan(data)
    plan = _get(db, Plan, plan_id, "Plan")
    for k, v in data.model_dump().items():
        setattr(plan, k, v)
    db.commit()
    return plan


# ---------- Tax rules ----------
@router.get("/taxes", response_model=list[TaxOut])
def list_taxes(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return db.scalars(select(TaxRule).order_by(TaxRule.name)).all()


@router.post("/taxes", response_model=TaxOut, status_code=201)
def create_tax(data: TaxIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = TaxRule(**data.model_dump())
    db.add(rule)
    db.flush()
    set_default(db, rule)
    db.commit()
    return rule


@router.put("/taxes/{tax_id}", response_model=TaxOut)
def update_tax(tax_id: int, data: TaxIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = _get(db, TaxRule, tax_id, "Tax rule")
    for k, v in data.model_dump().items():
        setattr(rule, k, v)
    set_default(db, rule)
    db.commit()
    return rule


# ---------- Discount rules ----------
def _check_discount(db: Session, data: DiscountIn, rule_id: int | None = None):
    if data.discount_type == "percentage" and data.value > 100:
        raise HTTPException(400, "A percentage discount cannot exceed 100")
    if data.start_date and data.end_date and data.end_date < data.start_date:
        raise HTTPException(400, "Discount end date must be on or after its start date")
    if data.target_type == "product":
        if data.product_id is None or db.get(Product, data.product_id) is None:
            raise HTTPException(400, "A product discount needs a valid product")
    elif data.subscription_id is not None and db.get(Subscription, data.subscription_id) is None:
        raise HTTPException(400, "Subscription not found")
    clash = db.scalar(select(DiscountRule.id).where(DiscountRule.code == data.code))
    if clash and clash != rule_id:
        raise HTTPException(400, f"Discount code {data.code} already exists")


@router.get("/discounts", response_model=list[DiscountOut])
def list_discounts(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return db.scalars(select(DiscountRule).order_by(DiscountRule.id.desc())).all()


@router.post("/discounts", response_model=DiscountOut, status_code=201)
def create_discount(data: DiscountIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Only the admin can create discount rules."""
    _check_discount(db, data)
    payload = data.model_dump()
    if data.target_type == "subscription":
        payload["product_id"] = None
    else:
        payload["subscription_id"] = None
    rule = DiscountRule(**payload)
    db.add(rule)
    db.commit()
    return rule


@router.put("/discounts/{discount_id}", response_model=DiscountOut)
def update_discount(discount_id: int, data: DiscountIn, admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    rule = _get(db, DiscountRule, discount_id, "Discount rule")
    _check_discount(db, data, rule.id)
    payload = data.model_dump()
    payload["product_id" if data.target_type == "subscription" else "subscription_id"] = None
    for k, v in payload.items():
        setattr(rule, k, v)
    db.commit()
    return rule


@router.delete("/discounts/{discount_id}", status_code=204)
def deactivate_discount(discount_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _get(db, DiscountRule, discount_id, "Discount rule").is_active = False
    db.commit()
