from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from ..models import Invoice, Payment, Plan, Subscription, SubscriptionLine, User

# Factor that turns one billing period's amount into a monthly amount.
MONTHLY_FACTOR = {"daily": 30.0, "weekly": 52.0 / 12.0, "monthly": 1.0, "yearly": 1.0 / 12.0}


def summary(db: Session, *, date_from: date | None = None, date_to: date | None = None,
            plan_id: int | None = None, customer_id: int | None = None, today: date | None = None) -> dict:
    """Everything the finance lead asks at month end, computed with a handful of aggregate queries."""
    today = today or date.today()

    sub_filters = []
    if plan_id:
        sub_filters.append(Subscription.plan_id == plan_id)
    if customer_id:
        sub_filters.append(Subscription.customer_id == customer_id)

    status_counts = dict(db.execute(
        select(Subscription.status, func.count()).where(*sub_filters).group_by(Subscription.status)).all())

    # MRR: recurring line amounts (or plan cost when a subscription has no lines), normalised per month.
    active = [Subscription.status == "active", *sub_filters]
    line_totals = db.execute(
        select(Plan.billing_frequency, func.sum(SubscriptionLine.quantity * SubscriptionLine.unit_price))
        .select_from(Subscription).join(Plan).join(SubscriptionLine)
        .where(*active).group_by(Plan.billing_frequency)).all()
    has_lines = exists().where(SubscriptionLine.subscription_id == Subscription.id)
    plan_totals = db.execute(
        select(Plan.billing_frequency, func.sum(Plan.cost))
        .select_from(Subscription).join(Plan).where(*active, ~has_lines).group_by(Plan.billing_frequency)).all()
    mrr = sum((amt or 0) * MONTHLY_FACTOR[freq] for freq, amt in [*line_totals, *plan_totals])

    inv_filters = []
    if customer_id:
        inv_filters.append(Invoice.customer_id == customer_id)
    if plan_id:
        inv_filters.append(Invoice.subscription_id.in_(select(Subscription.id).where(Subscription.plan_id == plan_id)))
    period_inv = list(inv_filters)
    if date_from:
        period_inv.append(Invoice.issue_date >= date_from)
    if date_to:
        period_inv.append(Invoice.issue_date <= date_to)

    invoiced = db.execute(
        select(func.count(), func.coalesce(func.sum(Invoice.total_amount), 0))
        .where(Invoice.status.in_(("confirmed", "paid")), *period_inv)).one()

    open_inv = [Invoice.status == "confirmed", Invoice.balance_due > 0, *inv_filters]
    outstanding = db.execute(
        select(func.count(), func.coalesce(func.sum(Invoice.balance_due), 0)).where(*open_inv)).one()
    overdue = db.execute(
        select(func.count(), func.coalesce(func.sum(Invoice.balance_due), 0))
        .where(*open_inv, Invoice.due_date < today)).one()

    pay_filters = []
    if customer_id:
        pay_filters.append(Payment.customer_id == customer_id)
    if plan_id:
        pay_filters.append(Payment.invoice_id.in_(
            select(Invoice.id).join(Subscription).where(Subscription.plan_id == plan_id)))
    if date_from:
        pay_filters.append(Payment.payment_date >= date_from)
    if date_to:
        pay_filters.append(Payment.payment_date <= date_to)
    collected = db.execute(
        select(func.count(), func.coalesce(func.sum(Payment.amount), 0)).where(*pay_filters)).one()
    by_method = db.execute(
        select(Payment.payment_method, func.sum(Payment.amount)).where(*pay_filters)
        .group_by(Payment.payment_method)).all()

    # Last 12 months: invoiced vs collected, for the trend chart.
    start_month = (today.replace(day=1) - relativedelta(months=11))
    month = func.strftime("%Y-%m", Payment.payment_date)
    paid_by_month = dict(db.execute(
        select(month, func.sum(Payment.amount))
        .where(Payment.payment_date >= start_month, *pay_filters)
        .group_by(month)).all())
    imonth = func.strftime("%Y-%m", Invoice.issue_date)
    billed_by_month = dict(db.execute(
        select(imonth, func.sum(Invoice.total_amount))
        .where(Invoice.issue_date >= start_month, Invoice.status.in_(("confirmed", "paid")), *inv_filters)
        .group_by(imonth)).all())
    months = [(start_month + relativedelta(months=i)).strftime("%Y-%m") for i in range(12)]

    by_plan = db.execute(
        select(Plan.name, func.count(Subscription.id))
        .select_from(Subscription).join(Plan).where(*active).group_by(Plan.name)
        .order_by(func.count(Subscription.id).desc())).all()

    return {
        "active_subscriptions": status_counts.get("active", 0),
        "subscriptions_by_status": status_counts,
        "mrr": round(mrr, 2),
        "arr": round(mrr * 12, 2),
        "invoiced_count": invoiced[0],
        "invoiced_amount": round(invoiced[1], 2),
        "revenue_collected": round(collected[1], 2),
        "payments_count": collected[0],
        "outstanding_count": outstanding[0],
        "outstanding_amount": round(outstanding[1], 2),
        "overdue_count": overdue[0],
        "overdue_amount": round(overdue[1], 2),
        "collected_by_method": {m: round(a, 2) for m, a in by_method},
        "active_by_plan": [{"plan": n, "count": c} for n, c in by_plan],
        "trend": [{"month": m, "invoiced": round(billed_by_month.get(m, 0) or 0, 2),
                   "collected": round(paid_by_month.get(m, 0) or 0, 2)} for m in months],
    }


def overdue_invoices(db: Session, today: date | None = None, limit: int = 200) -> list[dict]:
    """Chase list: overdue invoices, oldest first, with who to call."""
    today = today or date.today()
    rows = db.execute(
        select(Invoice, User).join(User, Invoice.customer_id == User.id)
        .where(Invoice.status == "confirmed", Invoice.balance_due > 0, Invoice.due_date < today)
        .order_by(Invoice.due_date).limit(limit)).all()
    return [{
        "invoice_id": inv.id, "invoice_number": inv.invoice_number, "customer_id": user.id,
        "customer_name": user.name, "company_name": user.company_name, "email": user.email, "phone": user.phone,
        "due_date": inv.due_date, "days_overdue": (today - inv.due_date).days, "balance_due": inv.balance_due,
        "bucket": ("1-30" if (today - inv.due_date).days <= 30 else
                   "31-60" if (today - inv.due_date).days <= 60 else "60+"),
    } for inv, user in rows]
