from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Plan, Product, ProductVariant, QuotationTemplate, Subscription, SubscriptionEvent, SubscriptionLine, User,
)
from . import blackbox
from .common import next_number
from .tax_service import tax_rate_for_product

STEP = {
    "daily": relativedelta(days=1),
    "weekly": relativedelta(weeks=1),
    "monthly": relativedelta(months=1),
    "yearly": relativedelta(years=1),
}


def next_period_start(anchor: date, current: date, frequency: str) -> date:
    """Start of the period after `current`. Month/year steps are computed from the anchor
    (contract start) so a subscription starting on the 31st does not drift to the 28th."""
    if frequency == "monthly":
        months = (current.year - anchor.year) * 12 + (current.month - anchor.month)
        return anchor + relativedelta(months=months + 1)
    if frequency == "yearly":
        return anchor + relativedelta(years=current.year - anchor.year + 1)
    return current + STEP[frequency]


def build_line(db: Session, product_id: int, variant_id: int | None, quantity: int,
               unit_price: float | None) -> SubscriptionLine:
    product = db.get(Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(400, f"Product {product_id} not found or inactive")
    variant = None
    if variant_id is not None:
        variant = db.get(ProductVariant, variant_id)
        if variant is None or variant.product_id != product.id or not variant.is_active:
            raise HTTPException(400, f"Variant {variant_id} does not belong to product '{product.name}'")
    price = unit_price if unit_price is not None else (variant.effective_price if variant else product.sales_price)
    return SubscriptionLine(product=product, variant=variant, quantity=quantity, unit_price=round(price, 2),
                            tax_rate=tax_rate_for_product(db, product))


_EVENT_TEXT = {
    "send_quotation": ("quotation_sent", "Quotation sent to the customer"), "revert_to_draft": ("reverted_to_draft", "Quotation moved back to draft"),
    "confirm": ("confirmed", "Quotation confirmed"), "activate": ("activated", "Subscription activated; billing starts"),
    "self_service": ("self_service", "Customer subscribed online"), "pause": ("paused", "Subscription paused"),
    "resume": ("resumed", "Subscription resumed"), "auto_resume": ("resumed", "Subscription resumed automatically"),
    "renew": ("renewed", "Contract renewed"), "close": ("closed", "Subscription closed"),
    "auto_close": ("closed", "Closed automatically at expiry"), "cancel": ("cancelled", "Subscription cancelled"),
    "decline": ("declined", "Customer declined the quotation"),
}


def log_event(sub: Subscription, from_status: str | None, to_status: str, action: str, actor: User | None,
              on: date | None = None, data: dict | None = None):
    sub.events.append(SubscriptionEvent(from_status=from_status, to_status=to_status, action=action,
                                        actor_email=actor.email if actor else "system"))
    if sub.id is not None and action in _EVENT_TEXT:   # 'create' is recorded once the subscription has an id
        kind, text = _EVENT_TEXT[action]
        data = {"from": from_status, "to": to_status, **(data or {})}
        if action == "pause":
            text += f" until {data['resume_on']}" if data.get("resume_on") else " until resumed manually"
            text += f" ({data['reason']})" if data.get("reason") else ""
        elif action == "renew" and data.get("new_expiry"):
            text += f"; now runs to {data['new_expiry']}"
        blackbox.record(sub, kind, text, actor=actor, on=on, data=data)


def _check_plan_available(plan: Plan, start: date):
    if not plan.is_active:
        raise HTTPException(400, f"Plan '{plan.name}' is not active")
    if plan.start_date and start < plan.start_date:
        raise HTTPException(400, f"Plan '{plan.name}' is only available from {plan.start_date}")
    if plan.end_date and start > plan.end_date:
        raise HTTPException(400, f"Plan '{plan.name}' was only available until {plan.end_date}")


def _get_customer(db: Session, customer_id: int) -> User:
    customer = db.get(User, customer_id)
    if customer is None or customer.role != "customer":
        raise HTTPException(400, "Customer not found")
    return customer


def create_subscription(db: Session, *, customer_id: int, plan_id: int, start_date: date,
                        expiry_date: date | None, payment_terms: str, notes: str | None,
                        lines: list, actor: User | None) -> Subscription:
    customer = _get_customer(db, customer_id)
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(400, "Plan not found")
    _check_plan_available(plan, start_date)
    if expiry_date and expiry_date <= start_date:
        raise HTTPException(400, "Expiry date must be after the start date")
    sub = Subscription(
        subscription_number=next_number(db, "subscription"), customer=customer, plan=plan,
        start_date=start_date, expiry_date=expiry_date, payment_terms=payment_terms, notes=notes, status="draft",
    )
    sub.lines = [build_line(db, l.product_id, l.variant_id, l.quantity, l.unit_price) for l in lines]
    log_event(sub, None, "draft", "create", actor)
    db.add(sub)
    db.flush()
    blackbox.record(sub, "created", f"Subscription {sub.subscription_number} created for {customer.company_name or customer.name} "
                    f"on {plan.name} ({plan.billing_frequency})", actor=actor, on=start_date, amount=sub.recurring_amount,
                    data={"plan": plan.name, "start": start_date, "expiry": expiry_date, "payment_terms": payment_terms,
                          "lines": [{"product": l.product.name, "variant": l.variant.label if l.variant else None,
                                     "qty": l.quantity, "unit_price": l.unit_price, "tax_rate": l.tax_rate} for l in sub.lines]})
    return sub


def create_from_template(db: Session, template: QuotationTemplate, customer_id: int, start_date: date | None,
                         actor: User) -> Subscription:
    start = start_date or date.today()
    sub = create_subscription(
        db, customer_id=customer_id, plan_id=template.plan_id, start_date=start,
        expiry_date=start + relativedelta(months=template.contract_months) - timedelta(days=1),
        payment_terms=template.payment_terms, notes=template.notes, lines=template.lines, actor=actor,
    )
    sub.template_id = template.id
    sub.quotation_valid_until = date.today() + timedelta(days=template.validity_days)
    return sub


def update_subscription(db: Session, sub: Subscription, data, actor: User) -> Subscription:
    if sub.status not in ("draft", "quotation"):
        raise HTTPException(400, "Only draft or quotation subscriptions can be edited")
    if data.start_date is not None:
        _check_plan_available(sub.plan, data.start_date)
        sub.start_date = data.start_date
    if data.expiry_date is not None:
        sub.expiry_date = data.expiry_date
    if sub.expiry_date and sub.expiry_date <= sub.start_date:
        raise HTTPException(400, "Expiry date must be after the start date")
    if data.payment_terms is not None:
        sub.payment_terms = data.payment_terms
    if data.notes is not None:
        sub.notes = data.notes
    if data.lines is not None:
        sub.lines = [build_line(db, l.product_id, l.variant_id, l.quantity, l.unit_price) for l in data.lines]
    db.flush()
    blackbox.record(sub, "terms_changed", f"Terms updated: recurring amount now {sub.recurring_amount:,.2f}", actor=actor,
                    amount=sub.recurring_amount,
                    data={"start": sub.start_date, "expiry": sub.expiry_date, "payment_terms": sub.payment_terms,
                          "lines": [{"product": l.product.name, "qty": l.quantity, "unit_price": l.unit_price} for l in sub.lines]})
    return sub


# action -> (allowed source states, target state, who may perform it)
TRANSITIONS = {
    "send_quotation": ({"draft"}, "quotation", {"admin", "staff"}),
    "revert_to_draft": ({"quotation"}, "draft", {"admin", "staff"}),
    "confirm": ({"quotation"}, "confirmed", {"admin", "staff", "customer"}),
    "activate": ({"confirmed"}, "active", {"admin", "staff"}),
    "pause": ({"active"}, "paused", {"admin", "staff", "customer"}),
    "resume": ({"paused"}, "active", {"admin", "staff", "customer"}),
    "renew": ({"active", "paused"}, None, {"admin", "staff", "customer"}),
    "close": ({"active", "paused"}, "closed", {"admin", "staff", "customer"}),
    "cancel": ({"draft", "quotation", "confirmed"}, "closed", {"admin", "staff"}),
    "decline": ({"quotation"}, "closed", {"customer"}),
}


def _policy_block(sub: Subscription, action: str, today: date) -> str | None:
    """Return a reason the plan's lifecycle policy forbids this action, or None."""
    plan = sub.plan
    if action == "pause" and not plan.allow_pause:
        return f"Plan '{plan.name}' does not allow pausing"
    if action == "renew":
        if not plan.allow_renewal:
            return f"Plan '{plan.name}' does not allow renewal"
        if sub.expiry_date is None:
            return "Subscription has no expiry date to renew"
    if action == "close":
        expired = sub.expiry_date is not None and sub.expiry_date < today
        if not expired and not plan.allow_early_close:
            return f"Plan '{plan.name}' does not allow closing before the expiry date"
    if action == "confirm" and sub.quotation_valid_until and sub.quotation_valid_until < today:
        return f"Quotation expired on {sub.quotation_valid_until}"
    return None


def allowed_actions(sub: Subscription, role: str, today: date | None = None) -> list[str]:
    today = today or date.today()
    return [a for a, (src, _, roles) in TRANSITIONS.items()
            if sub.status in src and role in roles and _policy_block(sub, a, today) is None]


def transition(db: Session, sub: Subscription, action: str, actor: User, today: date | None = None,
               resume_on: date | None = None, reason: str | None = None) -> Subscription:
    today = today or date.today()
    if action not in TRANSITIONS:
        raise HTTPException(400, f"Unknown action '{action}'")
    src, target, roles = TRANSITIONS[action]
    if actor.role not in roles:
        raise HTTPException(403, f"Your role cannot perform '{action}'")
    if sub.status not in src:
        raise HTTPException(400, f"Cannot {action.replace('_', ' ')} a subscription in '{sub.status}' state")
    blocked = _policy_block(sub, action, today)
    if blocked:
        raise HTTPException(400, blocked)

    previous = sub.status
    if action == "send_quotation" and sub.quotation_valid_until is None:
        sub.quotation_valid_until = today + timedelta(days=30)
    elif action == "confirm":
        total_qty = sum(l.quantity for l in sub.lines) if sub.lines else 1
        if total_qty < sub.plan.min_quantity:
            raise HTTPException(400, f"Plan '{sub.plan.name}' requires a minimum quantity of "
                                     f"{sub.plan.min_quantity} (this subscription has {total_qty})")
    elif action == "activate":
        sub.next_billing_date = sub.start_date
    elif action == "pause":
        limit = sub.plan.max_pause_days
        if resume_on is not None and resume_on <= today:
            raise HTTPException(400, "The resume date must be in the future")
        if limit:
            resume_on = resume_on or today + timedelta(days=limit)
            if (resume_on - today).days > limit:
                raise HTTPException(400, f"Plan '{sub.plan.name}' allows pauses of at most {limit} days")
        sub.paused_at, sub.resume_on, sub.pause_reason = today, resume_on, (reason or None)
    elif action == "resume":
        _resume(sub, today)
    elif action == "renew":
        # Extend by the length of the current term (e.g. a 12-month contract renews for 12 more months).
        next_term_start = sub.expiry_date + timedelta(days=1)
        term = relativedelta(next_term_start, sub.term_start or sub.start_date)
        sub.term_start = next_term_start
        sub.expiry_date = next_term_start + term - timedelta(days=1)
    if target in ("closed",):
        sub.closed_at = today
        sub.next_billing_date = None
        sub.paused_at = sub.resume_on = sub.pause_reason = None
    if target:
        sub.status = target
    extra = {"resume_on": sub.resume_on, "reason": sub.pause_reason} if action == "pause" else \
            {"new_expiry": sub.expiry_date} if action == "renew" else {}
    log_event(sub, previous, sub.status, action, actor, on=today, data=extra)
    db.flush()
    return sub


def _resume(sub: Subscription, today: date) -> None:
    # Periods spent paused are not billed: billing restarts from the resume day at the earliest.
    if sub.next_billing_date is None or sub.next_billing_date < today:
        sub.next_billing_date = today
    sub.paused_at = sub.resume_on = sub.pause_reason = None


def auto_resume_due(db: Session, today: date) -> int:
    """Resume paused subscriptions whose scheduled resume date has arrived (billed from that date)."""
    subs = db.scalars(select(Subscription).where(Subscription.status == "paused", Subscription.resume_on <= today)).all()
    for sub in subs:
        resumed_on = sub.resume_on
        _resume(sub, resumed_on)
        sub.status = "active"
        log_event(sub, "paused", "active", "auto_resume", None, on=resumed_on)
    db.flush()
    return len(subs)


def auto_close_expired(db: Session, today: date) -> int:
    """Close subscriptions whose plan says they end on their own once the expiry date has passed."""
    subs = db.scalars(
        select(Subscription).join(Plan)
        .where(Subscription.status.in_(("active", "paused")), Subscription.expiry_date < today,
               Plan.auto_close_on_expiry.is_(True))
    ).all()
    for sub in subs:
        previous = sub.status
        sub.status, sub.closed_at, sub.next_billing_date = "closed", today, None
        sub.paused_at = sub.resume_on = sub.pause_reason = None
        log_event(sub, previous, "closed", "auto_close", None, on=today)
    db.flush()
    return len(subs)
