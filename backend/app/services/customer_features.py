"""Customer-window features: Renewal Lock, Price Change Guardian, Personal Timeline and the QR Pass."""
import base64
import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone

import qrcode
import qrcode.image.svg
from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import config
from ..models import DiscountRule, Invoice, PriceChange, PriceNotice, Product, Subscription, SubscriptionLine, User
from . import blackbox
from .analytics_service import MONTHLY_FACTOR
from .common import send_email
from .subscription_service import next_period_start

LOCK_MONTHS = 12
PERIOD = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}
MIN_NOTICE_DAYS = 1      # the admin picks the date; 30 days is the default offered in the UI


def _today() -> date:
    return date.today()


# ---------- Renewal Lock ----------
def lock_end_for(sub: Subscription, today: date) -> date:
    """A lock covers the next renewal: through the end of the next term for fixed-term contracts,
    otherwise 12 months from today."""
    if sub.expiry_date and sub.expiry_date >= today:
        return sub.expiry_date + relativedelta(months=LOCK_MONTHS)
    return today + relativedelta(months=LOCK_MONTHS) - timedelta(days=1)


def is_locked(sub: Subscription, on: date | None = None) -> bool:
    return bool(sub.price_lock_until and sub.price_lock_until >= (on or _today()))


def lock_block(sub: Subscription, today: date) -> str | None:
    if sub.status not in ("active", "paused"):
        return "Only active or paused subscriptions can be locked"
    if is_locked(sub, today):
        return f"Prices are already locked until {sub.price_lock_until}"
    return None


def renewal_lock(db: Session, sub: Subscription, actor: User, today: date | None = None) -> Subscription:
    today = today or _today()
    reason = lock_block(sub, today)
    if reason:
        raise HTTPException(400, reason)
    sub.price_locked_at, sub.price_lock_until = today, lock_end_for(sub, today)
    deferred = 0
    for n in db.scalars(select(PriceNotice).where(PriceNotice.subscription_id == sub.id, PriceNotice.status == "scheduled")):
        if n.effective_on <= sub.price_lock_until:
            n.effective_on = sub.price_lock_until + timedelta(days=1)
            deferred += 1
    blackbox.record(sub, "renewal_locked", f"Renewal Lock: prices frozen until {sub.price_lock_until}"
                    + (f"; {deferred} scheduled price change{'s' if deferred != 1 else ''} deferred" if deferred else ""),
                    actor=actor, on=today, amount=sub.recurring_amount,
                    data={"until": sub.price_lock_until, "deferred_changes": deferred,
                          "locked_prices": [{"product": l.product.name, "unit_price": l.unit_price} for l in sub.lines]})
    db.flush()
    return sub


def release_lock(db: Session, sub: Subscription, actor: User, today: date | None = None) -> Subscription:
    today = today or _today()
    if not is_locked(sub, today):
        raise HTTPException(400, "This subscription has no active Renewal Lock")
    sub.price_lock_until = sub.price_locked_at = None
    for n in db.scalars(select(PriceNotice).where(PriceNotice.subscription_id == sub.id, PriceNotice.status == "scheduled")):
        n.effective_on = max(n.change.effective_on, today)
    blackbox.record(sub, "renewal_unlocked", "Renewal Lock released by Brightloop", actor=actor, on=today)
    db.flush()
    return sub


# ---------- Price changes ----------
def schedule_price_change(db: Session, product: Product, new_price: float, effective_on: date, note: str | None,
                          actor: User, today: date | None = None) -> PriceChange:
    today = today or _today()
    if effective_on < today + timedelta(days=MIN_NOTICE_DAYS):
        raise HTTPException(400, "A price change needs at least one day's notice")
    if round(new_price, 2) == round(product.sales_price, 2):
        raise HTTPException(400, "The new price is the same as the current price")
    if db.scalar(select(PriceChange.id).where(PriceChange.product_id == product.id, PriceChange.status == "scheduled")):
        raise HTTPException(400, f"{product.name} already has a scheduled price change; cancel it first")
    change = PriceChange(product=product, old_price=product.sales_price, new_price=round(new_price, 2), announced_on=today,
                         effective_on=effective_on, note=note, created_by=actor.email)
    db.add(change)
    ratio = new_price / product.sales_price if product.sales_price else None
    lines = db.scalars(select(SubscriptionLine).join(Subscription).where(
        SubscriptionLine.product_id == product.id,
        Subscription.status.in_(("active", "paused", "confirmed", "quotation")))).all()
    by_sub: dict[int, list[PriceNotice]] = {}
    for line in lines:
        sub = line.subscription
        # Negotiated prices move by the same percentage as the list price.
        new_unit = round(line.unit_price * ratio, 2) if ratio else round(new_price + (line.variant.surcharge if line.variant else 0), 2)
        when = effective_on
        if is_locked(sub, effective_on):
            when = sub.price_lock_until + timedelta(days=1)
        n = PriceNotice(change=change, subscription_id=sub.id, line_id=line.id, old_unit=line.unit_price, new_unit=new_unit,
                        quantity=line.quantity, effective_on=when)
        db.add(n)
        by_sub.setdefault(sub.id, []).append(n)
    db.flush()
    for sid, notices in by_sub.items():
        sub = db.get(Subscription, sid)
        delta = sum((n.new_unit - n.old_unit) * n.quantity for n in notices)
        when = min(n.effective_on for n in notices)
        locked = is_locked(sub, effective_on)
        blackbox.record(sub, "price_change_notice",
                        f"Notice: {product.name} changes from {notices[0].old_unit:,.2f} to {notices[0].new_unit:,.2f} per unit "
                        f"from {when}" + (" (deferred by your Renewal Lock)" if locked else ""),
                        actor=actor, on=today, amount=delta, data={"product": product.name, "effective_on": when, "delta_per_period": delta,
                                                                    "deferred_by_lock": locked})
        send_email(db, sub.customer.email, f"Price update for {product.name} on {sub.subscription_number}",
                   f"Hello {sub.customer.name},\n\n{product.name} will change from {notices[0].old_unit:,.2f} to {notices[0].new_unit:,.2f} "
                   f"per unit on {sub.subscription_number}, effective {when}. That's {delta:+,.2f} per {PERIOD[sub.plan.billing_frequency]} "
                   f"at your current quantity.\n\n" + ("Your Renewal Lock protects you until then.\n\n" if locked else
                   "You can lock your current price through your next renewal from the Price Guardian page in your customer portal.\n\n")
                   + "Brightloop Software")
    return change


def cancel_price_change(db: Session, change: PriceChange, actor: User) -> PriceChange:
    if change.status != "scheduled":
        raise HTTPException(400, f"This price change is already {change.status}")
    change.status = "cancelled"
    subs = set()
    for n in change.notices:
        if n.status == "scheduled":
            n.status = "cancelled"
            subs.add(n.subscription_id)
    for sid in subs:
        blackbox.record(db.get(Subscription, sid), "price_change_cancelled",
                        f"Scheduled price change for {change.product.name} withdrawn", actor=actor)
    db.flush()
    return change


def apply_due_price_changes(db: Session, as_of: date) -> int:
    """Called at the start of every billing run: move lines to their new price once their notice takes effect."""
    applied = 0
    for n in db.scalars(select(PriceNotice).join(Subscription).where(
            PriceNotice.status == "scheduled", PriceNotice.effective_on <= as_of)).all():
        sub = n.subscription
        if sub.status == "closed":
            n.status = "cancelled"
            continue
        old = n.line.unit_price
        n.line.unit_price = n.new_unit
        n.status = "applied"
        applied += 1
        blackbox.record(sub, "price_changed", f"{n.line.product.name} now {n.new_unit:,.2f} per unit (was {old:,.2f})",
                        on=n.effective_on, amount=(n.new_unit - old) * n.line.quantity,
                        data={"product": n.line.product.name, "old_unit": old, "new_unit": n.new_unit})
    for c in db.scalars(select(PriceChange).where(PriceChange.status == "scheduled", PriceChange.effective_on <= as_of)).all():
        c.product.sales_price = c.new_price     # new customers pay the new list price from now on
        c.status = "applied"
    db.flush()
    return applied


def price_changes_out(db: Session) -> list[dict]:
    rows = db.scalars(select(PriceChange).options(selectinload(PriceChange.notices)).order_by(PriceChange.id.desc())).all()
    return [{"id": c.id, "product_id": c.product_id, "product_name": c.product.name, "old_price": c.old_price, "new_price": c.new_price,
             "announced_on": c.announced_on, "effective_on": c.effective_on, "note": c.note, "status": c.status,
             "subscriptions": len({n.subscription_id for n in c.notices}),
             "deferred": len({n.subscription_id for n in c.notices if n.effective_on > c.effective_on}),
             "applied": sum(1 for n in c.notices if n.status == "applied")} for c in rows]


# ---------- estimates shared by Guardian and Timeline ----------
def estimate_period(sub: Subscription, on: date, notices: list[PriceNotice]) -> tuple[float, float]:
    """(untaxed, taxed) amount for a billing period starting `on`, using any price change in force by then.
    Discounts are not included."""
    upcoming = {n.line_id: n for n in notices if n.status == "scheduled" and n.effective_on <= on}
    if not sub.lines:
        base = sub.plan.cost
        return round(base, 2), round(base, 2)
    untaxed = taxed = 0.0
    for l in sub.lines:
        unit = upcoming[l.id].new_unit if l.id in upcoming else l.unit_price
        amt = unit * l.quantity
        untaxed += amt
        taxed += amt * (1 + l.tax_rate / 100)
    return round(untaxed, 2), round(taxed, 2)


def _customer_subs(db: Session, customer: User) -> list[Subscription]:
    return list(db.scalars(select(Subscription).where(Subscription.customer_id == customer.id)
                           .options(selectinload(Subscription.lines), selectinload(Subscription.plan)).order_by(Subscription.id)))


def _notices_for(db: Session, sub_ids: list[int]) -> list[PriceNotice]:
    if not sub_ids:
        return []
    return list(db.scalars(select(PriceNotice).where(PriceNotice.subscription_id.in_(sub_ids), PriceNotice.status == "scheduled")
                           .options(selectinload(PriceNotice.change), selectinload(PriceNotice.line))))


# ---------- Price Change Guardian ----------
def guardian(db: Session, customer: User, today: date | None = None) -> dict:
    today = today or _today()
    subs = _customer_subs(db, customer)
    live = [s for s in subs if s.status in ("active", "paused")]
    notices = _notices_for(db, [s.id for s in subs])
    changes, alerts, offers, forecasts = [], [], [], []

    for s in subs:
        mine = [n for n in notices if n.subscription_id == s.id]
        factor = MONTHLY_FACTOR[s.plan.billing_frequency]
        for n in mine:
            per_period = (n.new_unit - n.old_unit) * n.quantity
            lock_until = lock_end_for(s, today)
            could_save = 0.0
            if s in live and not is_locked(s, today) and n.effective_on <= lock_until:
                months = (lock_until.year - n.effective_on.year) * 12 + lock_until.month - n.effective_on.month + 1
                could_save = max(0.0, per_period * factor * months)
            changes.append({
                "subscription_id": s.id, "subscription_number": s.subscription_number, "product": n.line.product.name,
                "old_unit": n.old_unit, "new_unit": n.new_unit, "quantity": n.quantity,
                "change_pct": round((n.new_unit / n.old_unit - 1) * 100, 1) if n.old_unit else None,
                "per_period": round(per_period, 2), "per_month": round(per_period * factor, 2), "per_year": round(per_period * factor * 12, 2),
                "announced_on": n.change.announced_on, "change_effective_on": n.change.effective_on, "your_effective_on": n.effective_on,
                "deferred_by_lock": n.effective_on > n.change.effective_on, "days_until": (n.effective_on - today).days,
                "lock_would_save": round(could_save, 2), "note": n.change.note,
            })

    # Discounts that made the last invoice cheaper but are about to stop.
    for s in live:
        last = db.scalar(select(Invoice).where(Invoice.subscription_id == s.id, Invoice.status != "cancelled")
                         .order_by(Invoice.issue_date.desc()).limit(1))
        if last and last.discount_rule_id:
            rule = db.get(DiscountRule, last.discount_rule_id)
            ending = rule and (not rule.is_active or (rule.end_date and rule.end_date <= today + timedelta(days=45))
                               or (rule.max_uses and rule.current_uses >= rule.max_uses))
            if ending:
                alerts.append({"tone": "amber", "subscription_number": s.subscription_number,
                               "title": f"Your {rule.code} discount is ending",
                               "body": f"It took {last.discount_amount:,.2f} off your last invoice"
                                       + (f" and ends on {rule.end_date}" if rule.end_date else " and has run out")
                                       + ". Expect your next invoice to be that much higher."})
        if s.status == "paused" and s.resume_on and s.resume_on <= today + timedelta(days=30):
            alerts.append({"tone": "blue", "subscription_number": s.subscription_number, "title": "Billing restarts soon",
                           "body": f"{s.subscription_number} resumes on {s.resume_on}; the first invoice after your pause is issued that day."})
        if is_locked(s, today) and s.price_lock_until <= today + timedelta(days=45):
            alerts.append({"tone": "amber", "subscription_number": s.subscription_number, "title": "Your Renewal Lock ends soon",
                           "body": f"Prices on {s.subscription_number} are locked until {s.price_lock_until}. Any deferred changes apply after that."})

    # Next invoice forecast and lock offers.
    for s in live:
        when = s.resume_on if s.status == "paused" and s.resume_on else s.next_billing_date
        if when:
            untaxed, taxed = estimate_period(s, when, [n for n in notices if n.subscription_id == s.id])
            last = db.scalar(select(Invoice).where(Invoice.subscription_id == s.id, Invoice.status != "cancelled")
                             .order_by(Invoice.issue_date.desc()).limit(1))
            forecasts.append({"subscription_id": s.id, "subscription_number": s.subscription_number, "plan": s.plan.name, "on": when,
                              "estimate": taxed, "last_total": last.total_amount if last else None,
                              "change": round(taxed - last.total_amount, 2) if last else None})
        block = lock_block(s, today)
        offers.append({"subscription_id": s.id, "subscription_number": s.subscription_number, "plan": s.plan.name,
                       "locked": is_locked(s, today), "locked_until": s.price_lock_until if is_locked(s, today) else None,
                       "can_lock": block is None, "reason": block, "lock_until": lock_end_for(s, today) if block is None else None,
                       "recurring_amount": s.recurring_amount, "frequency": s.plan.billing_frequency,
                       "would_save": round(sum(c["lock_would_save"] for c in changes if c["subscription_id"] == s.id), 2)})

    exposure = sum(c["per_year"] for c in changes if not c["deferred_by_lock"])
    protected = sum(c["per_year"] for c in changes if c["deferred_by_lock"])
    status = "clear" if not changes and not alerts else "protected" if changes and exposure == 0 else "attention"
    return {"status": status, "changes": sorted(changes, key=lambda c: c["your_effective_on"]), "alerts": alerts,
            "forecasts": forecasts, "locks": offers, "yearly_exposure": round(exposure, 2), "yearly_protected": round(protected, 2)}


# ---------- Personal timeline ----------
def timeline(db: Session, customer: User, today: date | None = None, horizon_months: int = 6) -> dict:
    today = today or _today()
    subs = _customer_subs(db, customer)
    notices = _notices_for(db, [s.id for s in subs])
    items = []
    for s in subs:
        for e in blackbox.entries(db, s.id, include_internal=False):
            items.append({"date": e.occurred_on, "kind": e.event_type, "title": e.summary, "amount": e.amount,
                          "subscription_number": s.subscription_number, "subscription_id": s.id, "future": False})
    end = today + relativedelta(months=horizon_months)
    for s in subs:
        tag = {"subscription_number": s.subscription_number, "subscription_id": s.id, "future": True}
        mine = [n for n in notices if n.subscription_id == s.id]
        if s.status in ("active", "paused"):
            when = s.resume_on if s.status == "paused" and s.resume_on else s.next_billing_date if s.status == "active" else None
            if s.status == "paused" and s.resume_on:
                items.append({**tag, "date": s.resume_on, "kind": "resumes", "title": f"{s.subscription_number} resumes", "amount": None})
            for _ in range(24):
                if not when or when > end or (s.expiry_date and when > s.expiry_date):
                    break
                untaxed, taxed = estimate_period(s, when, mine)
                items.append({**tag, "date": when, "kind": "invoice_due", "amount": taxed,
                              "title": f"Invoice for {s.plan.name} (estimated, incl. tax)"})
                when = next_period_start(s.start_date, when, s.plan.billing_frequency)
            if s.expiry_date and today <= s.expiry_date <= end:
                ends = "renews or ends" if s.plan.allow_renewal else "ends"
                items.append({**tag, "date": s.expiry_date, "kind": "contract_end", "amount": None,
                              "title": f"Contract {ends}" + (" (closes automatically)" if s.plan.auto_close_on_expiry else "")})
            if is_locked(s, today) and s.price_lock_until <= end:
                items.append({**tag, "date": s.price_lock_until, "kind": "lock_ends", "amount": None, "title": "Renewal Lock ends"})
        if s.status == "quotation" and s.quotation_valid_until and s.quotation_valid_until >= today:
            items.append({**tag, "date": s.quotation_valid_until, "kind": "quote_expires", "amount": None,
                          "title": f"Quotation {s.subscription_number} valid until today"})
        for n in mine:
            if n.effective_on <= end:
                items.append({**tag, "date": n.effective_on, "kind": "price_change", "amount": round((n.new_unit - n.old_unit) * n.quantity, 2),
                              "title": f"{n.line.product.name} price {n.old_unit:,.2f} → {n.new_unit:,.2f}"})
    items.sort(key=lambda i: (i["date"], not i["future"]))
    upcoming = [i for i in items if i["future"]]
    return {"today": today, "items": items,
            "next_payment": next((i for i in upcoming if i["kind"] == "invoice_due"), None),
            "upcoming_total": round(sum(i["amount"] or 0 for i in upcoming if i["kind"] == "invoice_due"), 2),
            "horizon_months": horizon_months}


# ---------- QR Pass ----------
def _sign(payload: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(config.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()[:12]).decode().rstrip("=")


def pass_token(sub: Subscription) -> str:
    payload = f"{sub.id}.{sub.pass_version or 1}"
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + _sign(payload)


def read_token(db: Session, token: str) -> tuple[Subscription | None, str | None]:
    try:
        body, sig = token.split(".")
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        sid, version = (int(x) for x in payload.split("."))
    except Exception:
        return None, "This pass code is not valid"
    if not hmac.compare_digest(sig, _sign(payload)):
        return None, "This pass code is not valid"
    sub = db.get(Subscription, sid)
    if sub is None:
        return None, "This pass code is not valid"
    if version != (sub.pass_version or 1):
        return sub, "This pass has been replaced by a newer one"
    return sub, None


def pass_status(sub: Subscription, today: date) -> dict:
    if sub.status == "active":
        state, label = "valid", "Active"
    elif sub.status == "paused":
        state, label = "paused", "Paused"
    elif sub.status in ("draft", "quotation", "confirmed"):
        state, label = "pending", "Not started yet"
    else:
        state, label = "invalid", "Ended"
    if sub.status == "closed":
        through = sub.closed_at
    elif sub.expiry_date:
        through = sub.expiry_date
    else:
        through = sub.next_billing_date
    return {"state": state, "label": label, "valid_through": through, "rolling": sub.expiry_date is None and sub.status == "active"}


def pass_info(sub: Subscription, today: date | None = None) -> dict:
    today = today or _today()
    token = pass_token(sub)
    url = f"{config.APP_BASE_URL}/pass/{token}"
    svg = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1).to_string(encoding="unicode")
    return {"subscription_id": sub.id, "subscription_number": sub.subscription_number, "holder": sub.customer.company_name or sub.customer.name,
            "contact": sub.customer.name, "plan": sub.plan.name, "frequency": sub.plan.billing_frequency, "since": sub.start_date,
            "price_locked_until": sub.price_lock_until if is_locked(sub, today) else None,
            "products": [f"{l.quantity} × {l.product.name}" + (f" ({l.variant.label})" if l.variant else "") for l in sub.lines],
            "version": sub.pass_version or 1, "token": token, "verify_url": url, "qr_svg": svg, **pass_status(sub, today)}


def regenerate_pass(db: Session, sub: Subscription, actor: User) -> dict:
    sub.pass_version = (sub.pass_version or 1) + 1
    blackbox.record(sub, "pass_reissued", f"QR pass reissued (version {sub.pass_version}); earlier passes no longer verify", actor=actor)
    db.flush()
    return pass_info(sub)


def verify_pass(db: Session, token: str, today: date | None = None) -> dict:
    today = today or _today()
    sub, problem = read_token(db, token)
    checked = datetime.now(timezone.utc).replace(tzinfo=None)
    if sub is None or problem:
        return {"ok": False, "state": "invalid", "label": "Not valid", "message": problem, "checked_at": checked,
                "subscription_number": sub.subscription_number if sub else None}
    st = pass_status(sub, today)
    return {"ok": st["state"] == "valid", "message": None, "checked_at": checked, "subscription_number": sub.subscription_number,
            "holder": sub.customer.company_name or sub.customer.name, "plan": sub.plan.name, "since": sub.start_date, **st}
