from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_admin, require_staff
from ..database import get_db
from ..models import EmailLog, User
from ..schemas import EmailOut, RegisterIn, StaffIn, UserOut, UserUpdate
from .auth_router import create_user

router = APIRouter(prefix="/api", tags=["users"])


@router.post("/staff", response_model=UserOut, status_code=201)
def create_staff(data: StaffIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Only the admin can add a member of staff."""
    user = create_user(db, data, "staff")
    db.commit()
    return user


@router.get("/staff", response_model=list[UserOut])
def list_staff(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).where(User.role.in_(("admin", "staff"))).order_by(User.id)).all()


@router.get("/customers")
def list_customers(q: str | None = None, limit: int = 50, offset: int = 0,
                   user: User = Depends(require_staff), db: Session = Depends(get_db)):
    filters = [User.role == "customer"]
    if q:
        like = f"%{q.lower()}%"
        filters.append(or_(func.lower(User.name).like(like), func.lower(User.email).like(like),
                           func.lower(User.company_name).like(like)))
    total = db.scalar(select(func.count()).select_from(User).where(*filters))
    items = db.scalars(select(User).where(*filters).order_by(User.id.desc()).limit(min(limit, 500)).offset(offset))
    return {"total": total, "items": [UserOut.model_validate(u) for u in items]}


@router.post("/customers", response_model=UserOut, status_code=201)
def create_customer(data: RegisterIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """The internal team can open an account on a customer's behalf (e.g. a sales-led deal)."""
    customer = create_user(db, data, "customer")
    db.commit()
    return customer


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, actor: User = Depends(require_staff), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if actor.role != "admin" and target.role != "customer":
        raise HTTPException(403, "Only the admin can change staff accounts")
    if target.id == actor.id and data.is_active is False:
        raise HTTPException(400, "You cannot disable your own account")
    for field in data.model_fields_set:
        value = getattr(data, field)
        if field in ("name", "is_active") and value is None:
            continue
        setattr(target, field, value)
    db.commit()
    return target


@router.get("/emails", response_model=list[EmailOut])
def outbox(limit: int = 50, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Every email the system has sent (useful when SMTP is not configured)."""
    return db.scalars(select(EmailLog).order_by(EmailLog.id.desc()).limit(min(limit, 500))).all()
