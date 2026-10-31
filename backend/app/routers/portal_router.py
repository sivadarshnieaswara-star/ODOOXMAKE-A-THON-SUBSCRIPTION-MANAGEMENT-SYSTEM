"""Customer window: timeline, Price Change Guardian, Renewal Lock and QR passes; admin price changes."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin, require_customer, require_staff
from ..database import get_db
from ..models import PriceChange, Product, User
from ..serializers import sub_out
from ..services import customer_features as cf
from .subscription_router import load_subscription

router = APIRouter(prefix="/api", tags=["customer window"])


@router.get("/portal/timeline")
def my_timeline(months: int = 6, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return cf.timeline(db, user, horizon_months=max(1, min(months, 24)))


@router.get("/portal/account")
def my_account(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    """Header numbers for the customer's profile page."""
    return cf.account_summary(db, user)


@router.get("/portal/guardian")
def my_guardian(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return cf.guardian(db, user)


@router.post("/subscriptions/{sub_id}/renewal-lock")
def lock_renewal(sub_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = cf.renewal_lock(db, load_subscription(db, sub_id, user), user)
    db.commit()
    return sub_out(sub, user)


@router.delete("/subscriptions/{sub_id}/renewal-lock")
def unlock_renewal(sub_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    sub = cf.release_lock(db, load_subscription(db, sub_id, user), user)
    db.commit()
    return sub_out(sub, user)


@router.get("/subscriptions/{sub_id}/pass")
def subscription_pass(sub_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return cf.pass_info(load_subscription(db, sub_id, user))


@router.post("/subscriptions/{sub_id}/pass/regenerate")
def regenerate_subscription_pass(sub_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    info = cf.regenerate_pass(db, load_subscription(db, sub_id, user), user)
    db.commit()
    return info


@router.get("/pass/{token}")
def verify_pass(token: str, db: Session = Depends(get_db)):
    """Public: what a scanned QR pass shows. No amounts or contact details."""
    return cf.verify_pass(db, token)


class PriceChangeIn(BaseModel):
    product_id: int
    new_price: float = Field(ge=0)
    effective_on: date
    note: str | None = Field(default=None, max_length=255)


@router.get("/price-changes")
def list_price_changes(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return cf.price_changes_out(db)


@router.post("/price-changes", status_code=201)
def create_price_change(data: PriceChangeIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    product = db.get(Product, data.product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    change = cf.schedule_price_change(db, product, data.new_price, data.effective_on, data.note, admin)
    db.commit()
    return next(c for c in cf.price_changes_out(db) if c["id"] == change.id)


@router.post("/price-changes/{change_id}/cancel")
def cancel_price_change(change_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    change = db.get(PriceChange, change_id)
    if change is None:
        raise HTTPException(404, "Price change not found")
    cf.cancel_price_change(db, change, admin)
    db.commit()
    return next(c for c in cf.price_changes_out(db) if c["id"] == change.id)
