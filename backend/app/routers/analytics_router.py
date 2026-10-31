from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..auth import require_staff_or_admin
from ..services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["Executive Analytics"])

@router.get("/overview")
def get_financial_kpi_overview(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    plan_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin)
):
    """
    Returns executive financial dashboard metrics: Active Subscriptions, MRR, ARR,
    Total Cash Collected, Total Outstanding Dues, and Overdue Invoices.
    Guaranteed sub-2-second query execution time.
    """
    return AnalyticsService.get_financial_overview(
        db=db,
        start_date=start_date,
        end_date=end_date,
        plan_id=plan_id
    )

@router.get("/plans-distribution")
@router.get("/plans")
def get_subscriptions_by_plan(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin)
):
    """Returns subscriber distribution across plans."""
    return AnalyticsService.get_plan_distribution(db)
