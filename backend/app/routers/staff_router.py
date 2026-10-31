from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_admin, require_staff
from ..database import get_db
from ..models import EmailLog, User
from ..schemas import EmailOut, EmailSendTestIn, RegisterIn, StaffIn, UserOut, UserUpdate
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


@router.post("/emails/test", response_model=EmailOut)
def send_test_email_endpoint(data: EmailSendTestIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Send a diagnostic test email to verify SMTP configuration and delivery."""
    from .. import config
    from ..services.mail_service import _build_html_wrapper, send_email

    html_content = f"<p>{data.body}</p>"
    html = _build_html_wrapper(
        title=data.subject,
        body_content=html_content,
        action_url=config.APP_BASE_URL,
        action_label="Open Brightloop Platform",
    )
    entry = send_email(db, data.to_email, data.subject, data.body, html_body=html)
    db.commit()
    return entry


@router.get("/settings/mail")
def get_mail_settings(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Retrieve dynamic system mail settings and SMTP connection status."""
    from .. import config
    from ..services.mail_service import get_mail_setting

    target_email = get_mail_setting(db, "mail_target_email", config.SMTP_USER or "saisrikar1220@gmail.com")
    redirect_dummy = get_mail_setting(db, "mail_redirect_dummy", "true").lower() in ("true", "1", "yes")

    return {
        "smtp_configured": bool(config.SMTP_HOST and config.SMTP_USER),
        "smtp_host": config.SMTP_HOST or "Offline (Outbox Only)",
        "smtp_port": config.SMTP_PORT,
        "smtp_from": config.SMTP_FROM,
        "target_email": target_email,
        "redirect_dummy": redirect_dummy,
    }


@router.post("/settings/mail")
def update_mail_settings(data: dict, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Update dynamic mail routing preferences (target email and dummy redirect flag)."""
    from ..services.mail_service import set_mail_setting

    if "target_email" in data:
        set_mail_setting(db, "mail_target_email", str(data["target_email"]).strip())
    if "redirect_dummy" in data:
        set_mail_setting(db, "mail_redirect_dummy", "true" if data["redirect_dummy"] else "false")
    db.commit()

    return {"message": "Mail settings updated successfully"}


@router.post("/settings/update-customer-emails")
def update_all_customer_emails(data: dict, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Update all dummy customer accounts to use the configured email address for billing and alerts."""
    target_email = str(data.get("target_email") or "").strip()
    if not target_email or "@" not in target_email:
        raise HTTPException(400, "Valid target_email is required")

    customers = db.scalars(select(User).where(User.role == "customer")).all()
    count = 0
    for c in customers:
        c.billing_email = target_email
        count += 1
    db.commit()

    return {
        "message": f"Updated {count} customer accounts to receive billing emails at {target_email}",
        "updated_count": count,
        "target_email": target_email,
    }
