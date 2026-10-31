from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user, require_customer, require_staff
from ..database import get_db
from ..models import Plan, QuotationTemplate, QuotationTemplateLine, Subscription, User
from ..schemas import (
    PortalSubscribeIn, SubActionIn, SubLineIn, SubscriptionIn, SubscriptionOut, SubscriptionUpdate, TemplateIn, TemplateOut,
    TemplateUseIn,
)
from ..serializers import sub_out, template_out
from ..services import billing_service
from ..services import subscription_service as svc

router = APIRouter(prefix="/api", tags=["subscriptions"])


def load_subscription(db: Session, sub_id: int, user: User) -> Subscription:
    sub = db.get(Subscription, sub_id)
    # Customers only ever see their own subscriptions; a 404 avoids revealing other numbers.
    if sub is None or (user.role == "customer" and sub.customer_id != user.id):
        raise HTTPException(404, "Subscription not found")
    return sub


# ---------- Subscriptions ----------
@router.get("/subscriptions")
def list_subscriptions(status: str | None = None, plan_id: int | None = None, customer_id: int | None = None,
                       q: str | None = None, limit: int = 50, offset: int = 0,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    filters = []
    if user.role == "customer":
        filters.append(Subscription.customer_id == user.id)
    elif customer_id:
        filters.append(Subscription.customer_id == customer_id)
    if status:
        filters.append(Subscription.status == status)
    if plan_id:
        filters.append(Subscription.plan_id == plan_id)
    if q:
        like = f"%{q.lower()}%"
        filters.append(or_(func.lower(Subscription.subscription_number).like(like),
                           Subscription.customer_id.in_(select(User.id).where(or_(
                               func.lower(User.name).like(like), func.lower(User.company_name).like(like),
                               func.lower(User.email).like(like))))))
    total = db.scalar(select(func.count()).select_from(Subscription).where(*filters))
    subs = db.scalars(
        select(Subscription).where(*filters)
        .options(selectinload(Subscription.customer), selectinload(Subscription.plan),
                 selectinload(Subscription.lines))
        .order_by(Subscription.id.desc()).limit(min(limit, 500)).offset(offset)).all()
    return {"total": total, "items": [sub_out(s, user, detail=False) for s in subs]}


@router.get("/subscriptions/{sub_id}", response_model=SubscriptionOut)
def get_subscription(sub_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return sub_out(load_subscription(db, sub_id, user), user)


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
def create_subscription(data: SubscriptionIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    sub = svc.create_subscription(db, customer_id=data.customer_id, plan_id=data.plan_id,
                                  start_date=data.start_date, expiry_date=data.expiry_date,
                                  payment_terms=data.payment_terms, notes=data.notes, lines=data.lines, actor=user)
    db.commit()
    return sub_out(sub, user)


@router.patch("/subscriptions/{sub_id}", response_model=SubscriptionOut)
def update_subscription(sub_id: int, data: SubscriptionUpdate, user: User = Depends(require_staff),
                        db: Session = Depends(get_db)):
    sub = svc.update_subscription(db, load_subscription(db, sub_id, user), data, user)
    db.commit()
    return sub_out(sub, user)


@router.post("/subscriptions/{sub_id}/actions/{action}", response_model=SubscriptionOut)
def subscription_action(sub_id: int, action: str, data: SubActionIn | None = None,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = data or SubActionIn()
    sub = svc.transition(db, load_subscription(db, sub_id, user), action, user, resume_on=data.resume_on, reason=data.reason)
    db.commit()
    return sub_out(sub, user)


@router.post("/subscriptions/{sub_id}/bill-now")
def bill_now(sub_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    inv = billing_service.bill_now(db, load_subscription(db, sub_id, user))
    db.commit()
    return {"invoice_id": inv.id, "invoice_number": inv.invoice_number}


# ---------- Quotation templates ----------
def _template_lines(db: Session, lines: list) -> list[QuotationTemplateLine]:
    out = []
    for l in lines:
        built = svc.build_line(db, l.product_id, l.variant_id, l.quantity, l.unit_price)  # validates refs
        out.append(QuotationTemplateLine(product_id=built.product.id, variant_id=l.variant_id,
                                         quantity=l.quantity, unit_price=l.unit_price))
    return out


def _get_template(db: Session, template_id: int) -> QuotationTemplate:
    t = db.get(QuotationTemplate, template_id)
    if t is None:
        raise HTTPException(404, "Quotation template not found")
    return t


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return [template_out(t) for t in db.scalars(select(QuotationTemplate).order_by(QuotationTemplate.name))]


@router.post("/templates", response_model=TemplateOut, status_code=201)
def create_template(data: TemplateIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    if db.get(Plan, data.plan_id) is None:
        raise HTTPException(400, "Plan not found")
    t = QuotationTemplate(**data.model_dump(exclude={"lines"}))
    t.lines = _template_lines(db, data.lines)
    db.add(t)
    db.commit()
    return template_out(t)


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(template_id: int, data: TemplateIn, user: User = Depends(require_staff),
                    db: Session = Depends(get_db)):
    t = _get_template(db, template_id)
    if db.get(Plan, data.plan_id) is None:
        raise HTTPException(400, "Plan not found")
    for k, v in data.model_dump(exclude={"lines"}).items():
        setattr(t, k, v)
    t.lines = _template_lines(db, data.lines)
    db.commit()
    return template_out(t)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: int, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    t = _get_template(db, template_id)
    for sub in db.scalars(select(Subscription).where(Subscription.template_id == t.id)):
        sub.template_id = None
    db.delete(t)
    db.commit()


@router.post("/templates/{template_id}/use", response_model=SubscriptionOut, status_code=201)
def use_template(template_id: int, data: TemplateUseIn, user: User = Depends(require_staff),
                 db: Session = Depends(get_db)):
    """Create a ready-to-send subscription quote from the template in one step."""
    sub = svc.create_from_template(db, _get_template(db, template_id), data.customer_id, data.start_date, user)
    db.commit()
    return sub_out(sub, user)


# ---------- Customer self-service ----------
@router.post("/portal/subscribe", response_model=SubscriptionOut, status_code=201)
def portal_subscribe(data: PortalSubscribeIn, user: User = Depends(require_customer),
                     db: Session = Depends(get_db)):
    """A customer subscribes to a plan themselves; it starts today and is billed from today."""
    plan = db.get(Plan, data.plan_id)
    if plan is None or not plan.is_active:
        raise HTTPException(400, "Plan not available")
    if data.quantity < plan.min_quantity:
        raise HTTPException(400, f"Plan '{plan.name}' requires at least {plan.min_quantity} units")
    sub = svc.create_subscription(
        db, customer_id=user.id, plan_id=plan.id, start_date=date.today(), expiry_date=None,
        payment_terms="immediate", notes="Self-service signup",
        lines=[SubLineIn(product_id=data.product_id, variant_id=data.variant_id, quantity=data.quantity)],
        actor=user)
    # Self-service skips the sales quote: record each step so the history stays complete.
    for target, action in (("quotation", "self_service"), ("confirmed", "confirm"), ("active", "activate")):
        svc.log_event(sub, sub.status, target, action, user)
        sub.status = target
    sub.next_billing_date = sub.start_date
    db.commit()
    return sub_out(sub, user)
