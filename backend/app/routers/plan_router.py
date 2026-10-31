from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Plan, User, BillingFrequency
from ..schemas import PlanCreate, PlanUpdate, PlanResponse
from ..auth import require_admin, get_current_user

router = APIRouter(prefix="/api/plans", tags=["Subscription Plans"])

VALID_FREQUENCIES = [
    BillingFrequency.DAILY,
    BillingFrequency.WEEKLY,
    BillingFrequency.MONTHLY,
    BillingFrequency.YEARLY
]

@router.get("", response_model=List[PlanResponse])
def list_plans(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists all active subscription plans with their lifecycle policies."""
    plans = db.query(Plan).filter(Plan.is_active == True).all()
    return [PlanResponse.model_validate(p) for p in plans]

@router.post("", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(
    plan_in: PlanCreate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Creates a new recurring plan with configurable lifecycle policies.
    Restricted strictly to Admin.
    """
    freq = plan_in.billing_frequency.lower()
    if freq not in VALID_FREQUENCIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid billing_frequency '{plan_in.billing_frequency}'. Allowed: {VALID_FREQUENCIES}"
        )
    if plan_in.cost < 0:
        raise HTTPException(status_code=400, detail="Plan cost cannot be negative.")
    if plan_in.min_quantity < 1:
        raise HTTPException(status_code=400, detail="Minimum quantity must be at least 1.")

    plan = Plan(
        name=plan_in.name,
        cost=plan_in.cost,
        billing_frequency=freq,
        min_quantity=plan_in.min_quantity,
        start_date=plan_in.start_date,
        end_date=plan_in.end_date,
        auto_close_on_expiry=plan_in.auto_close_on_expiry,
        allow_early_close=plan_in.allow_early_close,
        allow_pause=plan_in.allow_pause,
        allow_renewal=plan_in.allow_renewal,
        is_active=True
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return PlanResponse.model_validate(plan)

@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves single plan details and policy settings."""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")
    return PlanResponse.model_validate(plan)

@router.put("/{plan_id}", response_model=PlanResponse)
def update_plan(
    plan_id: int,
    plan_in: PlanUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    """Updates plan details and policies. Restricted to Admin."""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")

    if plan_in.name is not None:
        plan.name = plan_in.name
    if plan_in.cost is not None:
        if plan_in.cost < 0:
            raise HTTPException(status_code=400, detail="Plan cost cannot be negative.")
        plan.cost = plan_in.cost
    if plan_in.billing_frequency is not None:
        freq = plan_in.billing_frequency.lower()
        if freq not in VALID_FREQUENCIES:
            raise HTTPException(status_code=400, detail=f"Invalid billing_frequency. Allowed: {VALID_FREQUENCIES}")
        plan.billing_frequency = freq
    if plan_in.min_quantity is not None:
        if plan_in.min_quantity < 1:
            raise HTTPException(status_code=400, detail="Minimum quantity must be at least 1.")
        plan.min_quantity = plan_in.min_quantity
    if plan_in.start_date is not None:
        plan.start_date = plan_in.start_date
    if plan_in.end_date is not None:
        plan.end_date = plan_in.end_date
    if plan_in.auto_close_on_expiry is not None:
        plan.auto_close_on_expiry = plan_in.auto_close_on_expiry
    if plan_in.allow_early_close is not None:
        plan.allow_early_close = plan_in.allow_early_close
    if plan_in.allow_pause is not None:
        plan.allow_pause = plan_in.allow_pause
    if plan_in.allow_renewal is not None:
        plan.allow_renewal = plan_in.allow_renewal
    if plan_in.is_active is not None:
        plan.is_active = plan_in.is_active

    db.commit()
    db.refresh(plan)
    return PlanResponse.model_validate(plan)
