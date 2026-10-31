"""Subscription black box: an append-only, hash-chained flight recorder for billing events.

Every subscription gets its own chain. Each entry stores the hash of the entry before it, and its own
hash covers all of its fields plus that previous hash. Changing, deleting or reordering any entry
therefore breaks every hash after it, which `verify` detects.
"""
import hashlib
import json
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from ..models import BlackBoxEntry, Invoice, Payment, Subscription, User


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def genesis(sub: Subscription) -> str:
    """Chain anchor, bound to the subscription number so chains can't be swapped between subscriptions."""
    return hashlib.sha256(f"brightloop-blackbox:{sub.subscription_number}".encode()).hexdigest()


def entry_hash(e: BlackBoxEntry) -> str:
    payload = json.dumps([e.subscription_id, e.seq, e.occurred_on.isoformat(), e.recorded_at.isoformat(timespec="microseconds"),
                          e.event_type, e.actor_email, e.summary, None if e.amount is None else round(e.amount, 2),
                          e.data_json, bool(e.internal), e.prev_hash], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def record(sub: Subscription, event_type: str, summary: str, *, actor: User | None = None, on: date | None = None,
           amount: float | None = None, data: dict | None = None, internal: bool = False) -> BlackBoxEntry | None:
    """Append one event to the subscription's recorder (uses the subscription's own session)."""
    db = object_session(sub)
    if db is None:
        return None
    if sub.id is None:
        db.flush()
    db.flush()  # earlier entries from this unit of work must be visible to find the chain head
    last = db.scalar(select(BlackBoxEntry).where(BlackBoxEntry.subscription_id == sub.id)
                     .order_by(BlackBoxEntry.seq.desc()).limit(1))
    e = BlackBoxEntry(subscription_id=sub.id, seq=(last.seq + 1) if last else 1, occurred_on=on or date.today(),
                      recorded_at=_now(), event_type=event_type, actor_email=actor.email if actor else "system",
                      summary=summary[:500], amount=None if amount is None else round(amount, 2),
                      data_json=json.dumps(data or {}, sort_keys=True, default=str), internal=internal,
                      prev_hash=last.hash if last else genesis(sub))
    e.hash = entry_hash(e)
    db.add(e)
    return e


def entries(db: Session, sub_id: int, include_internal: bool = True) -> list[BlackBoxEntry]:
    stmt = select(BlackBoxEntry).where(BlackBoxEntry.subscription_id == sub_id).order_by(BlackBoxEntry.seq)
    if not include_internal:
        stmt = stmt.where(BlackBoxEntry.internal.is_(False))
    return list(db.scalars(stmt))


def verify(db: Session, sub: Subscription) -> dict:
    """Walk the whole chain; report the first entry whose link or contents don't check out."""
    chain = entries(db, sub.id)
    prev = genesis(sub)
    for i, e in enumerate(chain, start=1):
        if e.seq != i:
            return {"ok": False, "entries": len(chain), "broken_at": e.seq, "reason": f"entry {i} is missing or out of order"}
        if e.prev_hash != prev:
            return {"ok": False, "entries": len(chain), "broken_at": e.seq, "reason": "link to the previous entry is broken"}
        if entry_hash(e) != e.hash:
            return {"ok": False, "entries": len(chain), "broken_at": e.seq, "reason": "entry contents were changed after recording"}
        prev = e.hash
    return {"ok": True, "entries": len(chain), "broken_at": None, "reason": None, "head": prev}


def entry_out(e: BlackBoxEntry) -> dict:
    return {"seq": e.seq, "occurred_on": e.occurred_on, "recorded_at": e.recorded_at, "event_type": e.event_type,
            "actor_email": e.actor_email, "summary": e.summary, "amount": e.amount, "data": json.loads(e.data_json or "{}"),
            "internal": e.internal, "prev_hash": e.prev_hash, "hash": e.hash}


# ---------- reconstruction for subscriptions that existed before the recorder ----------
_STATUS_ACTIONS = {
    "create": ("created", "Subscription created"), "send_quotation": ("quotation_sent", "Quotation sent"),
    "revert_to_draft": ("reverted_to_draft", "Quotation moved back to draft"), "confirm": ("confirmed", "Quotation confirmed"),
    "activate": ("activated", "Subscription activated"), "self_service": ("self_service", "Customer subscribed online"),
    "pause": ("paused", "Subscription paused"), "resume": ("resumed", "Subscription resumed"),
    "auto_resume": ("resumed", "Subscription resumed automatically"), "renew": ("renewed", "Contract renewed"),
    "close": ("closed", "Subscription closed"), "auto_close": ("closed", "Closed automatically at expiry"),
    "cancel": ("cancelled", "Subscription cancelled"), "decline": ("declined", "Customer declined the quotation"),
}


def backfill_missing(db: Session) -> int:
    """Give every subscription without a recorder a reconstructed history from existing records."""
    have = set(db.scalars(select(BlackBoxEntry.subscription_id).distinct()))
    subs = [s for s in db.scalars(select(Subscription).order_by(Subscription.id)) if s.id not in have]
    for sub in subs:
        rows = []
        for ev in sub.events:
            kind, text = _STATUS_ACTIONS.get(ev.action, (ev.action, ev.action.replace("_", " ").capitalize()))
            when = {"create": sub.start_date, "send_quotation": sub.start_date, "confirm": sub.start_date,
                    "activate": sub.start_date, "self_service": sub.start_date, "close": sub.closed_at,
                    "auto_close": sub.closed_at, "cancel": sub.closed_at, "decline": sub.closed_at,
                    "pause": sub.paused_at}.get(ev.action) or ev.created_at.date()
            rows.append((min(when, ev.created_at.date()) if ev.action == "create" else when, 0, kind, text, None,
                         {"from": ev.from_status, "to": ev.to_status}, ev.actor_email))
        for inv in db.scalars(select(Invoice).where(Invoice.subscription_id == sub.id)):
            rows.append((inv.issue_date, 1, "invoice_issued", f"Invoice {inv.invoice_number} issued for "
                         f"{inv.period_start} to {inv.period_end}", inv.total_amount,
                         {"invoice": inv.invoice_number, "subtotal": inv.subtotal, "discount": inv.discount_amount,
                          "discount_code": inv.discount_code, "tax": inv.tax_amount}, "system"))
            if inv.sent_at:
                rows.append((inv.sent_at.date(), 3, "invoice_sent", f"Invoice {inv.invoice_number} emailed to the customer", None,
                             {"invoice": inv.invoice_number}, "system"))
            if inv.status == "cancelled":
                rows.append((inv.issue_date, 2, "invoice_cancelled", f"Invoice {inv.invoice_number} cancelled", None,
                             {"invoice": inv.invoice_number}, "system"))
            for p in inv.payments:
                rows.append((p.payment_date, 4, "payment_received", f"Payment {p.payment_number} received by "
                             f"{p.payment_method.replace('_', ' ')} for {inv.invoice_number}", p.amount,
                             {"invoice": inv.invoice_number, "payment": p.payment_number, "method": p.payment_method}, p.recorded_by or "system"))
            if inv.status == "paid" and inv.paid_at:
                rows.append((inv.paid_at, 5, "invoice_paid", f"Invoice {inv.invoice_number} settled in full", None,
                             {"invoice": inv.invoice_number}, "system"))
        rows.sort(key=lambda r: (r[0], r[1]))
        for when, _, kind, text, amount, data, actor_email in rows:
            e = record(sub, kind, text, on=when, amount=amount, data={**data, "reconstructed": True})
            if e:
                e.actor_email = actor_email or "system"
                e.hash = entry_hash(e)
    db.commit()
    return len(subs)


# ---------- report ----------
def report_data(db: Session, sub: Subscription, customer_copy: bool = False, today: date | None = None) -> dict:
    """Everything the flight recorder report shows: verified chain, lifetime figures, incidents, timeline."""
    today = today or date.today()
    check = verify(db, sub)
    chain = entries(db, sub.id, include_internal=not customer_copy)
    invoices = list(db.scalars(select(Invoice).where(Invoice.subscription_id == sub.id).order_by(Invoice.issue_date)))
    live = [i for i in invoices if i.status != "cancelled"]
    payments = list(db.scalars(select(Payment).join(Invoice).where(Invoice.subscription_id == sub.id).order_by(Payment.payment_date)))

    billed = sum(i.total_amount for i in live)
    collected = sum(p.amount for p in payments)
    late_payments = [(p, (p.payment_date - p.invoice.due_date).days) for p in payments if p.payment_date > p.invoice.due_date]
    overdue = [i for i in live if i.status == "confirmed" and i.balance_due > 0 and i.due_date < today]
    pauses = [e for e in chain if e.event_type == "paused"]
    days_paused = 0
    paused_from = None
    for e in chain:
        if e.event_type == "paused":
            paused_from = e.occurred_on
        elif e.event_type == "resumed" and paused_from:
            days_paused += (e.occurred_on - paused_from).days
            paused_from = None
    if paused_from:
        days_paused += (today - paused_from).days
    end = sub.closed_at or today
    on_time = sum(1 for i in live if i.status == "paid" and i.paid_at and i.paid_at <= i.due_date)
    paid_count = sum(1 for i in live if i.status == "paid")

    incidents = []
    for i in overdue:
        incidents.append({"level": "critical", "on": i.due_date, "title": f"{i.invoice_number} overdue",
                          "detail": f"{i.balance_due:,.2f} unpaid, {(today - i.due_date).days} days past due"})
    for p, days in late_payments:
        incidents.append({"level": "warning", "on": p.payment_date, "title": f"Late payment on {p.invoice.invoice_number}",
                          "detail": f"{p.amount:,.2f} received {days} days after the due date"})
    for e in chain:
        if e.event_type in ("paused", "closed", "cancelled", "declined", "invoice_cancelled"):
            incidents.append({"level": "info" if e.event_type == "paused" else "warning", "on": e.occurred_on,
                              "title": e.event_type.replace("_", " ").capitalize(), "detail": e.summary})
    incidents.sort(key=lambda x: x["on"], reverse=True)

    # Flight data: cumulative billed vs collected over the life of the subscription.
    points, cum_b, cum_c = [], 0.0, 0.0
    events = sorted([(i.issue_date, "b", i.total_amount) for i in live] + [(p.payment_date, "c", p.amount) for p in payments])
    for d, kind, amt in events:
        if kind == "b":
            cum_b += amt
        else:
            cum_c += amt
        points.append({"on": d, "billed": round(cum_b, 2), "collected": round(cum_c, 2)})
    chart = _chart(points)

    return {
        "sub": sub, "customer": sub.customer, "plan": sub.plan, "verification": check, "customer_copy": customer_copy,
        "entries": [entry_out(e) for e in chain], "generated_at": _now(), "today": today,
        "report_id": (check.get("head") or "")[:16].upper(),
        "stats": {
            "events": check["entries"], "invoices": len(live), "payments": len(payments), "billed": billed, "collected": collected,
            "outstanding": sum(i.balance_due for i in live if i.status == "confirmed"),
            "discounts": sum(i.discount_amount for i in live), "tax": sum(i.tax_amount for i in live),
            "days_on_book": max(0, (end - sub.start_date).days), "pauses": len(pauses), "days_paused": days_paused,
            "renewals": sum(1 for e in chain if e.event_type == "renewed"),
            "on_time_rate": (on_time / paid_count) if paid_count else None, "late_payments": len(late_payments),
            "collection_rate": (collected / billed) if billed else None,
        },
        "incidents": incidents[:30], "chart": chart,
    }


def _chart(points: list[dict]) -> dict | None:
    if len(points) < 2:
        return None
    W, H, L, B, T = 700, 200, 56, 26, 10
    d0, d1 = points[0]["on"], points[-1]["on"]
    span = max(1, (d1 - d0).days)
    top = max(p["billed"] for p in points) * 1.08 or 1
    x = lambda d: L + (W - L - 10) * (d - d0).days / span
    y = lambda v: T + (H - T - B) * (1 - v / top)
    def path(key):  # step line: values hold until the next event
        out, prev = [], None
        for p in points:
            if prev is not None:
                out.append(f"L{x(p['on']):.1f},{y(prev):.1f}")
            out.append(f"{'M' if not out else 'L'}{x(p['on']):.1f},{y(p[key]):.1f}")
            prev = p[key]
        return " ".join(out)
    grid = [{"y": y(top * f), "label": f"{top * f:,.0f}"} for f in (0, .25, .5, .75, 1)]
    return {"w": W, "h": H, "billed": path("billed"), "collected": path("collected"), "grid": grid,
            "start": d0, "end": d1, "left": L}
