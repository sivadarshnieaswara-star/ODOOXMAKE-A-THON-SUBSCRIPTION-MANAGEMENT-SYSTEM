"""Automated business recommendations.

Each rule looks at the live data and, when it finds something worth doing, returns a recommendation
with a priority, an estimated dollar impact, the records involved and (where it's safe) an action
that can be carried out in one click. Low-risk actions can also run together as "autopilot".
"""
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    AutomationLog, DiscountRule, Invoice, Plan, Product, RecommendationDismissal, Subscription, SubscriptionEvent, User,
)
from .analytics_service import MONTHLY_FACTOR
from .billing_service import confirm_invoice, run_billing
from .common import send_email

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
# Actions that only send emails or do routine bookkeeping; autopilot may run these unattended.
SAFE_ACTIONS = {"send_reminders", "send_renewal_reminders", "send_quote_followups", "confirm_drafts", "run_billing"}


def _mrr(sub: Subscription) -> float:
    return sub.recurring_amount * MONTHLY_FACTOR[sub.plan.billing_frequency]


def _name(u: User) -> str:
    return u.company_name or u.name


def _rec(key, category, priority, title, detail, impact, impact_label, items, action=None):
    return {"key": key, "category": category, "priority": priority, "title": title, "detail": detail,
            "impact": round(impact, 2), "impact_label": impact_label, "items": items[:25], "item_count": len(items),
            "action": action}


def build(db: Session, today: date | None = None) -> list[dict]:
    today = today or date.today()
    recs: list[dict] = []
    active = db.scalars(select(Subscription).where(Subscription.status.in_(("active", "paused")))
                        .options(selectinload(Subscription.lines), selectinload(Subscription.plan),
                                 selectinload(Subscription.customer))).all()
    total_mrr = sum(_mrr(s) for s in active if s.status == "active") or 1.0

    # --- Collections: overdue invoices -------------------------------------------------------
    overdue = db.scalars(select(Invoice).where(Invoice.status == "confirmed", Invoice.balance_due > 0, Invoice.due_date < today)
                         .options(selectinload(Invoice.customer)).order_by(Invoice.due_date)).all()
    if overdue:
        amount = sum(i.balance_due for i in overdue)
        old = [i for i in overdue if (today - i.due_date).days > 30]
        recs.append(_rec(
            "collections-overdue", "Collections", "high" if old or amount > 0.05 * total_mrr else "medium",
            f"Chase {len(overdue)} overdue invoice{'s' if len(overdue) != 1 else ''}",
            f"{len(old)} are more than 30 days late. A reminder with the balance and due date usually recovers most of it.",
            amount, "outstanding",
            [{"label": f"{i.invoice_number} · {_name(i.customer)}", "value": i.balance_due, "note": f"{(today - i.due_date).days} days late",
              "invoice_id": i.id} for i in overdue],
            {"type": "send_reminders", "label": "Email payment reminders", "ids": [i.id for i in overdue]}))

    # --- Billing: subscriptions due now / drafts waiting ---------------------------------------
    due = [s for s in active if s.status == "active" and s.next_billing_date and s.next_billing_date <= today]
    if due:
        recs.append(_rec(
            "billing-due", "Operations", "high", f"{len(due)} subscription{'s are' if len(due) != 1 else ' is'} due for billing",
            "Run billing to invoice them. It's idempotent, so nothing is billed twice.",
            sum(s.recurring_amount for s in due), "to invoice",
            [{"label": f"{s.subscription_number} · {_name(s.customer)}", "value": s.recurring_amount,
              "note": f"due {s.next_billing_date}", "subscription_id": s.id} for s in due],
            {"type": "run_billing", "label": "Run billing now"}))
    drafts = db.scalars(select(Invoice).where(Invoice.status == "draft").options(selectinload(Invoice.customer))).all()
    if drafts:
        recs.append(_rec(
            "billing-drafts", "Operations", "medium", f"Confirm {len(drafts)} draft invoice{'s' if len(drafts) != 1 else ''}",
            "Draft invoices aren't visible to customers and can't be paid until they're confirmed.",
            sum(i.total_amount for i in drafts), "waiting",
            [{"label": f"{i.invoice_number} · {_name(i.customer)}", "value": i.total_amount, "note": f"issued {i.issue_date}",
              "invoice_id": i.id} for i in drafts],
            {"type": "confirm_drafts", "label": "Confirm all drafts", "ids": [i.id for i in drafts]}))

    # --- Renewals: fixed-term contracts ending within 60 days ----------------------------------
    ending = [s for s in active if s.expiry_date and today <= s.expiry_date <= today + timedelta(days=60)]
    if ending:
        recs.append(_rec(
            "renewals-60d", "Renewals", "high" if any(s.expiry_date <= today + timedelta(days=21) for s in ending) else "medium",
            f"{len(ending)} contract{'s' if len(ending) != 1 else ''} end within 60 days",
            "Start renewal conversations now; contracts on auto-close plans will stop billing at expiry.",
            sum(_mrr(s) for s in ending) * 12, "ARR at stake",
            [{"label": f"{s.subscription_number} · {_name(s.customer)}", "value": _mrr(s) * 12, "note": f"ends {s.expiry_date}",
              "subscription_id": s.id} for s in sorted(ending, key=lambda s: s.expiry_date)],
            {"type": "send_renewal_reminders", "label": "Email renewal reminders", "ids": [s.id for s in ending]}))

    # --- Retention: long pauses and customers who are behind on payments -------------------------
    overdue_by_customer: dict[int, float] = {}
    for i in overdue:
        if (today - i.due_date).days > 30:
            overdue_by_customer[i.customer_id] = overdue_by_customer.get(i.customer_id, 0) + i.balance_due
    at_risk = [s for s in active if (s.status == "paused" and s.paused_at and (today - s.paused_at).days >= 45)
               or (s.status == "active" and s.customer_id in overdue_by_customer)]
    if at_risk:
        recs.append(_rec(
            "retention-at-risk", "Retention", "high", f"{len(at_risk)} account{'s' if len(at_risk) != 1 else ''} at risk of churning",
            "Long pauses and invoices more than 30 days late are the strongest early signs of churn. Reach out personally.",
            sum(_mrr(s) for s in at_risk), "MRR at risk",
            [{"label": f"{s.subscription_number} · {_name(s.customer)}", "value": _mrr(s),
              "note": (f"paused {(today - s.paused_at).days} days" if s.status == "paused"
                       else f"${overdue_by_customer[s.customer_id]:,.0f} overdue 30+ days"), "subscription_id": s.id}
             for s in sorted(at_risk, key=_mrr, reverse=True)],
            {"type": "send_checkins", "label": "Send check-in emails", "ids": [s.id for s in at_risk]}))

    # --- Growth: monthly customers who are good candidates for an annual plan -----------------
    late_customers = {i.customer_id for i in overdue}
    tenured = [s for s in active if s.status == "active" and s.plan.billing_frequency == "monthly"
               and (today - s.start_date).days >= 180 and s.customer_id not in late_customers]
    if tenured:
        recs.append(_rec(
            "growth-annual", "Growth", "medium",
            f"Offer annual billing to {len(tenured)} loyal monthly customer{'s' if len(tenured) != 1 else ''}",
            "They've paid on time for 6+ months. Locking them into an annual term (e.g. two months free) cuts churn and brings cash forward.",
            sum(_mrr(s) for s in tenured) * 12, "ARR to lock in",
            [{"label": f"{s.subscription_number} · {_name(s.customer)}", "value": _mrr(s) * 12,
              "note": f"customer for {(today - s.start_date).days // 30} months", "subscription_id": s.id}
             for s in sorted(tenured, key=_mrr, reverse=True)],
            {"type": "send_annual_offers", "label": "Email annual-plan offers", "ids": [s.id for s in tenured]}))

    addon = db.scalar(select(Product).where(Product.product_type == "addon", Product.is_active.is_(True))
                      .order_by(Product.sales_price.desc()))
    if addon:
        candidates = [s for s in active if s.status == "active"
                      and sum(l.quantity for l in s.lines) >= 10 and all(l.product_id != addon.id for l in s.lines)]
        if candidates:
            recs.append(_rec(
                "growth-upsell", "Growth", "low", f"Upsell {addon.name} to {len(candidates)} larger account{'s' if len(candidates) != 1 else ''}",
                f"These subscriptions have 10+ units but no {addon.name}. Teams this size get the most out of it.",
                addon.sales_price * len(candidates), "potential MRR",
                [{"label": f"{s.subscription_number} · {_name(s.customer)}", "value": addon.sales_price,
                  "note": f"{sum(l.quantity for l in s.lines)} units", "subscription_id": s.id} for s in candidates],
                {"type": "send_upsell_offers", "label": f"Email {addon.name} offer", "ids": [s.id for s in candidates],
                 "product_id": addon.id}))

    # --- Sales: quotations about to expire ----------------------------------------------------
    quotes = db.scalars(select(Subscription).where(Subscription.status == "quotation",
                                                   Subscription.quotation_valid_until.between(today, today + timedelta(days=7)))
                        .options(selectinload(Subscription.lines), selectinload(Subscription.plan),
                                 selectinload(Subscription.customer))).all()
    if quotes:
        recs.append(_rec(
            "sales-quotes-expiring", "Sales", "medium", f"{len(quotes)} quotation{'s' if len(quotes) != 1 else ''} expire this week",
            "Follow up before they lapse; an expired quote has to be re-issued.",
            sum(_mrr(s) * 12 for s in quotes), "ARR in pipeline",
            [{"label": f"{s.subscription_number} · {_name(s.customer)}", "value": _mrr(s) * 12,
              "note": f"valid until {s.quotation_valid_until}", "subscription_id": s.id} for s in quotes],
            {"type": "send_quote_followups", "label": "Email follow-ups", "ids": [s.id for s in quotes]}))

    # --- Pricing: discounts running out --------------------------------------------------------
    rules = db.scalars(select(DiscountRule).where(DiscountRule.is_active.is_(True))).all()
    expiring = [r for r in rules if (r.end_date and today <= r.end_date <= today + timedelta(days=14))
                or (r.max_uses and r.current_uses >= 0.8 * r.max_uses and r.current_uses < r.max_uses)]
    if expiring:
        recs.append(_rec(
            "pricing-discounts", "Pricing", "low", f"{len(expiring)} discount rule{'s' if len(expiring) != 1 else ''} about to run out",
            "Decide whether to extend them. Customers who expect the discount will see a higher next invoice.",
            0, "", [{"label": r.code, "value": None,
                     "note": (f"ends {r.end_date}" if r.end_date and r.end_date <= today + timedelta(days=14)
                              else f"{r.current_uses}/{r.max_uses} uses")} for r in expiring],
            {"type": "link", "label": "Review discounts", "href": "#/discounts"}))

    # --- Plans that churn much faster than the rest -------------------------------------------
    since = today - timedelta(days=180)
    closes = dict(db.execute(select(Subscription.plan_id, func.count()).join(SubscriptionEvent)
                             .where(SubscriptionEvent.action == "close", Subscription.closed_at >= since)
                             .group_by(Subscription.plan_id)).all())
    starts = dict(db.execute(select(Subscription.plan_id, func.count()).where(Subscription.start_date <= today,
                             Subscription.status.in_(("active", "paused", "closed"))).group_by(Subscription.plan_id)).all())
    rates = {pid: closes.get(pid, 0) / n for pid, n in starts.items() if n >= 8}
    if len(rates) >= 2:
        avg = sum(rates.values()) / len(rates)
        for pid, rate in rates.items():
            if avg > 0 and rate > 1.6 * avg and closes.get(pid, 0) >= 3:
                plan = db.get(Plan, pid)
                recs.append(_rec(
                    f"pricing-churn-plan-{pid}", "Pricing", "medium", f"'{plan.name}' loses customers faster than other plans",
                    f"{rate * 100:.0f}% of its subscriptions were cancelled in the last 6 months vs {avg * 100:.0f}% on average. "
                    "Review its price, onboarding or minimums.", 0, "",
                    [{"label": plan.name, "value": None, "note": f"{closes.get(pid, 0)} cancellations"}],
                    {"type": "link", "label": "Open plans", "href": "#/plans"}))

    # --- Concentration -------------------------------------------------------------------------
    by_customer: dict[int, float] = {}
    for s in active:
        if s.status == "active":
            by_customer[s.customer_id] = by_customer.get(s.customer_id, 0) + _mrr(s)
    if by_customer:
        cid, top = max(by_customer.items(), key=lambda kv: kv[1])
        if top / total_mrr > 0.25 and len(by_customer) > 1:
            u = db.get(User, cid)
            recs.append(_rec(
                "risk-concentration", "Retention", "medium", f"{_name(u)} is {top / total_mrr * 100:.0f}% of MRR",
                "Losing one customer this size would hurt. Assign an account owner and keep their renewal close.",
                top, "MRR concentrated", [{"label": _name(u), "value": top, "note": u.email}],
                {"type": "link", "label": "View subscriptions", "href": "#/subscriptions"}))

    dismissed = {d.key for d in db.scalars(select(RecommendationDismissal).where(RecommendationDismissal.until >= today))}
    for r in recs:
        r["dismissed"] = r["key"] in dismissed
        if r["action"]:
            r["action"]["safe"] = r["action"]["type"] in SAFE_ACTIONS
    recs.sort(key=lambda r: (r["dismissed"], PRIORITY_ORDER[r["priority"]], -r["impact"]))
    return recs


# ---------- actions ----------
def _email_subs(db: Session, ids: list[int], subject: str, body) -> int:
    n = 0
    for sub in db.scalars(select(Subscription).where(Subscription.id.in_(ids))):
        send_email(db, sub.customer.email, subject.format(sub=sub), body(sub))
        n += 1
    return n


def execute(db: Session, rec_key: str, actor: User, autopilot: bool = False, today: date | None = None) -> dict:
    """Carry out a recommendation's action. Re-reads the live recommendation so stale ids are never acted on."""
    today = today or date.today()
    rec = next((r for r in build(db, today) if r["key"] == rec_key), None)
    if rec is None or not rec["action"] or rec["action"]["type"] == "link":
        raise HTTPException(400, "That recommendation has no action to run (it may already be resolved)")
    a, kind = rec["action"], rec["action"]["type"]
    if kind == "send_reminders":
        n = 0
        for inv in db.scalars(select(Invoice).where(Invoice.id.in_(a["ids"]), Invoice.status == "confirmed")):
            send_email(db, inv.customer.email, f"Reminder: invoice {inv.invoice_number} is overdue",
                       f"Hello {inv.customer.name},\n\nInvoice {inv.invoice_number} for {inv.balance_due:,.2f} was due on {inv.due_date} "
                       f"and is now {(today - inv.due_date).days} days overdue. You can pay it in your Brightloop customer portal.\n\n"
                       "If you've already paid, please ignore this message.\n\nBrightloop Software")
            n += 1
        summary = f"Sent {n} payment reminder{'s' if n != 1 else ''}"
    elif kind == "confirm_drafts":
        n = 0
        for inv in db.scalars(select(Invoice).where(Invoice.id.in_(a["ids"]), Invoice.status == "draft")):
            confirm_invoice(inv)
            n += 1
        summary = f"Confirmed {n} draft invoice{'s' if n != 1 else ''}"
    elif kind == "run_billing":
        r = run_billing(db, today)
        summary = f"Billing run created {r['invoices_created']} invoice{'s' if r['invoices_created'] != 1 else ''}"
    elif kind == "send_renewal_reminders":
        n = _email_subs(db, a["ids"], "Your Brightloop contract {sub.subscription_number} is up for renewal",
                        lambda s: f"Hello {s.customer.name},\n\nYour {s.plan.name} contract ends on {s.expiry_date}. "
                                  "Reply to this email or renew from your customer portal to keep everything running without a gap.\n\nBrightloop Software")
        summary = f"Sent {n} renewal reminder{'s' if n != 1 else ''}"
    elif kind == "send_checkins":
        n = _email_subs(db, a["ids"], "Checking in on your Brightloop subscription",
                        lambda s: f"Hello {s.customer.name},\n\nWe noticed things have been quiet on {s.subscription_number}. "
                                  "Is there anything we can help with? Reply and your account manager will get back to you today.\n\nBrightloop Software")
        summary = f"Sent {n} check-in email{'s' if n != 1 else ''}"
    elif kind == "send_annual_offers":
        n = _email_subs(db, a["ids"], "Save with annual billing on {sub.subscription_number}",
                        lambda s: f"Hello {s.customer.name},\n\nThanks for being with us. Switching {s.subscription_number} to annual billing "
                                  f"would cost {s.recurring_amount * 10:,.2f} a year instead of {s.recurring_amount * 12:,.2f}: two months free. "
                                  "Reply to this email and we'll set it up.\n\nBrightloop Software")
        summary = f"Sent {n} annual-plan offer{'s' if n != 1 else ''}"
    elif kind == "send_upsell_offers":
        product = db.get(Product, a["product_id"])
        n = _email_subs(db, a["ids"], f"{product.name} for your team",
                        lambda s: f"Hello {s.customer.name},\n\nTeams your size get a lot out of {product.name}. It's {product.sales_price:,.2f} "
                                  f"a month on {s.subscription_number}. Reply to this email and we'll add it.\n\nBrightloop Software")
        summary = f"Sent {n} {product.name} offer{'s' if n != 1 else ''}"
    elif kind == "send_quote_followups":
        n = _email_subs(db, a["ids"], "Your Brightloop quotation {sub.subscription_number} expires soon",
                        lambda s: f"Hello {s.customer.name},\n\nYour quotation {s.subscription_number} for {s.plan.name} is valid until "
                                  f"{s.quotation_valid_until}. You can accept it from your customer portal.\n\nBrightloop Software")
        summary = f"Sent {n} quotation follow-up{'s' if n != 1 else ''}"
    else:
        raise HTTPException(400, f"Unknown action '{kind}'")

    db.add(AutomationLog(action=kind, summary=summary, actor_email=actor.email, autopilot=autopilot))
    # Acted on: hide it for a week so the same emails aren't sent twice by accident.
    dismiss(db, rec_key, days=7, commit=False)
    db.commit()
    return {"key": rec_key, "summary": summary}


def autopilot(db: Session, actor: User, today: date | None = None) -> list[dict]:
    """Run every safe, not-dismissed action. Recommendations are rebuilt after each step, so work one
    action creates (billing -> new drafts -> confirm them -> reminders) is picked up in the same run."""
    today = today or date.today()
    first = {"billing-due": 0, "billing-drafts": 1}
    done, done_keys = [], set()
    for _ in range(20):
        recs = sorted(build(db, today), key=lambda r: first.get(r["key"], 2))
        nxt = next((r for r in recs if r["key"] not in done_keys and not r["dismissed"]
                    and r["action"] and r["action"].get("safe")), None)
        if nxt is None:
            break
        done.append(execute(db, nxt["key"], actor, autopilot=True, today=today))
        done_keys.add(nxt["key"])
    if not done:
        db.add(AutomationLog(action="autopilot", summary="Autopilot ran: nothing needed doing", actor_email=actor.email, autopilot=True))
        db.commit()
    return done


def dismiss(db: Session, key: str, days: int = 30, commit: bool = True, today: date | None = None) -> None:
    today = today or date.today()
    row = db.get(RecommendationDismissal, key)
    if row:
        row.until = today + timedelta(days=days)
    else:
        db.add(RecommendationDismissal(key=key, until=today + timedelta(days=days)))
    if commit:
        db.commit()


def restore(db: Session, key: str) -> None:
    row = db.get(RecommendationDismissal, key)
    if row:
        db.delete(row)
        db.commit()


def activity(db: Session, limit: int = 30) -> list[AutomationLog]:
    return db.scalars(select(AutomationLog).order_by(AutomationLog.id.desc()).limit(limit)).all()
