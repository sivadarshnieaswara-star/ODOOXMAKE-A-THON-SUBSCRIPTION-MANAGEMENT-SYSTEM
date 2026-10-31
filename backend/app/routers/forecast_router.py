from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import require_admin, require_staff
from ..database import get_db
from ..models import User
from ..services import forecast_service, simulation_data

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


@router.get("")
def get_forecast(months: int = Query(12, ge=3, le=36), sims: int = Query(2000, ge=200, le=10000),
                 churn: float = Query(1.0, ge=0, le=3, description="Multiplier on fitted churn"),
                 growth: float = Query(1.0, ge=0, le=3, description="Multiplier on new-business rate"),
                 collection: float | None = Query(None, ge=0.3, le=1.0, description="Override collection rate"),
                 target_arr: float | None = Query(None, gt=0), seed: int = 42,
                 user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Monte Carlo revenue forecast fitted to this company's own history."""
    result = forecast_service.forecast(db, months=months, sims=sims, churn_mult=churn, growth_mult=growth,
                                       collection=collection, target_arr=target_arr, seed=seed)
    result["simulation_data_loaded"] = simulation_data.is_loaded(db)
    return result


class SimulationIn(BaseModel):
    months: int = Field(18, ge=3, le=36)
    customers: int = Field(140, ge=10, le=600)
    seed: int = 7


@router.post("/simulation-data")
def load_simulation_data(data: SimulationIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Play out past months of simulated customers so the forecast has real history to learn from."""
    return simulation_data.generate(db, months=data.months, customers=data.customers, seed=data.seed)
