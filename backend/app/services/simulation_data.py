"""Generate a realistic book of business by playing out past months one at a time.

Each simulated month: new customers sign up (at a rate that grows over time), the normal billing
engine invoices whatever is due, some monthly customers churn or buy more seats, annual contracts
renew or lapse, and customers pay according to their payment habits. Everything goes through the
same services the app uses, so the history is internally consistent.
"""
import random
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import hash_password
from ..models import Invoice, Plan, Product, ProductVariant, Subscription, User
from ..schemas import SubLineIn
from . import subscription_service as svc
from .billing_service import run_billing
from .payment_service import record_payment

SIM_DOMAIN = "sim.brightloop.test"

_PREFIX = ["Northwind", "Bluepeak", "Kite", "Silverline", "Harbor", "Lumen", "Cobalt", "Juniper", "Maple", "Orbit", "Pioneer",
           "Quartz", "Redwood", "Saffron", "Tidal", "Vertex", "Willow", "Zephyr", "Amber", "Banyan", "Cedar", "Delta", "Ember",
           "Fable", "Granite", "Helix", "Indigo", "Jasper", "Keystone", "Lotus", "Monsoon", "Nimbus", "Opal", "Prism"]
_SUFFIX = ["Retail", "Logistics", "Foods", "Clinics", "Studios", "Traders", "Labs", "Builders", "Textiles", "Motors",
           "Pharma", "Hotels", "Systems", "Exports", "Interiors", "Agro", "Finance", "Media"]
_FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vikram", "Isha", "Arjun", "Nisha", "Karthik", "Pooja",
          "Rahul", "Sneha", "Aditya", "Kavya", "Siddharth", "Lakshmi", "Varun", "Priya"]
_LAST = ["Iyer", "Sharma", "Reddy", "Nair", "Gupta", "Menon", "Patel", "Rao", "Das", "Kapoor", "Joshi", "Pillai"]
_METHODS = (["bank_transfer"] * 4) + (["upi"] * 3) + (["card"] * 2) + ["stripe"]


def is_loaded(db: Session) -> bool:
    return db.scalar(select(User.id).where(User.email.like(f"%@{SIM_DOMAIN}")).limit(1)) is not None


def _get_or_create(db: Session, model, name: str, **fields):
    obj = db.scalar(select(model).where(model.name == name))
    if obj is None:
        obj = model(name=name, **fields)
        db.add(obj)
        db.flush()
    return obj


def _catalog(db: Session) -> dict:
    """Reuse the demo catalog when it exists; otherwise create the few items the simulation needs."""
    erp = _get_or_create(db, Product, "Brightloop ERP Cloud", product_type="software", sales_price=1200, cost_price=310)
    if not erp.variants:
        erp.variants = [ProductVariant(attribute_name="Brand", variant_value="Standard Edition", surcharge=0),
                        ProductVariant(attribute_name="Brand", variant_value="Odoo Brand Edition", surcharge=560)]
        db.flush()
    odoo = next((v for v in erp.variants if v.surcharge > 0), erp.variants[0])
    return {
        "erp": erp, "odoo": odoo,
        "crm": _get_or_create(db, Product, "CRM Pro", product_type="software", sales_price=45, cost_price=8),
        "analytics": _get_or_create(db, Product, "Advanced Analytics Add-On", product_type="addon", sales_price=200, cost_price=40),
        "backup": _get_or_create(db, Product, "Daily Cloud Backup", product_type="addon", sales_price=60, cost_price=12),
        "monthly": _get_or_create(db, Plan, "Growth Monthly Plan", cost=500, billing_frequency="monthly", min_quantity=1,
                                  auto_close_on_expiry=False, allow_early_close=True, allow_pause=True, allow_renewal=True),
        "annual": _get_or_create(db, Plan, "Enterprise Annual Contract", cost=15000, billing_frequency="yearly", min_quantity=5,
                                 auto_close_on_expiry=True, allow_early_close=False, allow_pause=False, allow_renewal=True),
    }


def generate(db: Session, *, months: int = 18, customers: int = 140, seed: int = 7, today: date | None = None) -> dict:
    if is_loaded(db):
        raise HTTPException(400, "Simulation data is already loaded")
    today = today or date.today()
    rng = random.Random(seed)
    cat = _catalog(db)
    actor = db.scalar(select(User).where(User.role == "admin"))
    pw_hash, salt = hash_password("CustomerPass#2026")  # one hash shared by every simulated login

    first_month = (today - relativedelta(months=months)).replace(day=1)
    month_starts = [first_month + relativedelta(months=i) for i in range(months + 1)]
    # Sign-ups grow over time: later months are weighted more heavily.
    arrivals = rng.choices(range(len(month_starts)), weights=[1 + 0.12 * i for i in range(len(month_starts))], k=customers)

    profile: dict[int, str] = {}   # customer id -> payment habit
    stats = {"customers": 0, "subscriptions": 0, "churned": 0, "renewed": 0, "upsells": 0, "payments": 0}
    used_names: set[str] = set()

    for i, ms in enumerate(month_starts):
        me = min(today - timedelta(days=1), ms + relativedelta(months=1) - timedelta(days=1))
        if me < ms:
            break

        # 1. New customers this month.
        for _ in range(arrivals.count(i)):
            company = f"{rng.choice(_PREFIX)} {rng.choice(_SUFFIX)}"
            while company in used_names:
                company = f"{rng.choice(_PREFIX)} {rng.choice(_SUFFIX)} {rng.randint(2, 99)}"
            used_names.add(company)
            user = User(email=f"{company.lower().replace(' ', '.')}@{SIM_DOMAIN}", password_hash=pw_hash, password_salt=salt,
                        role="customer", name=f"{rng.choice(_FIRST)} {rng.choice(_LAST)}", company_name=company,
                        phone=f"+91 9{rng.randint(100000000, 999999999)}")
            db.add(user)
            db.flush()
            profile[user.id] = rng.choices(["prompt", "slow", "bad"], weights=[74, 21, 5])[0]
            stats["customers"] += 1

            start = ms + timedelta(days=rng.randint(0, max(0, (me - ms).days)))
            if rng.random() < 0.16:   # enterprise annual contract, priced per year
                plan, expiry, terms = cat["annual"], start + relativedelta(years=1) - timedelta(days=1), "net_30"
                lines = [SubLineIn(product_id=cat["erp"].id, variant_id=cat["odoo"].id, quantity=1, unit_price=1760 * 12),
                         SubLineIn(product_id=cat["crm"].id, quantity=rng.randint(10, 60), unit_price=45 * 12)]
                if rng.random() < 0.6:
                    lines.append(SubLineIn(product_id=cat["analytics"].id, quantity=1, unit_price=200 * 12))
            else:                      # monthly plan sized like a small or mid business
                plan, expiry, terms = cat["monthly"], None, rng.choice(["immediate", "net_15", "net_15", "net_30"])
                lines = [SubLineIn(product_id=cat["crm"].id, quantity=max(1, int(rng.lognormvariate(1.6, 0.7))))]
                if rng.random() < 0.18:
                    lines.append(SubLineIn(product_id=cat["erp"].id, quantity=1))
                if rng.random() < 0.35:
                    lines.append(SubLineIn(product_id=cat["analytics"].id, quantity=1))
                if rng.random() < 0.4:
                    lines.append(SubLineIn(product_id=cat["backup"].id, quantity=1))
            sub = svc.create_subscription(db, customer_id=user.id, plan_id=plan.id, start_date=start, expiry_date=expiry,
                                          payment_terms=terms, notes="Simulated customer", lines=lines, actor=actor)
            for action in ("send_quotation", "confirm", "activate"):
                svc.transition(db, sub, action, actor, today=start)
            stats["subscriptions"] += 1

        # 2. Annual contracts ending this month: most renew, the rest lapse and auto-close.
        for sub in db.scalars(select(Subscription).join(Plan).where(
                Subscription.status == "active", Plan.billing_frequency == "yearly",
                Subscription.expiry_date <= me, Subscription.notes == "Simulated customer")).all():
            if rng.random() < 0.82:
                svc.transition(db, sub, "renew", actor, today=sub.expiry_date)
                stats["renewed"] += 1

        # 3. Billing day for this month.
        run_billing(db, as_of=me, auto_confirm=True)

        # 4. Monthly customers churn (more likely early on) or buy more seats.
        for sub in db.scalars(select(Subscription).join(Plan).where(
                Subscription.status == "active", Plan.billing_frequency == "monthly",
                Subscription.start_date < ms, Subscription.notes == "Simulated customer")).all():
            age = (me.year - sub.start_date.year) * 12 + me.month - sub.start_date.month
            if rng.random() < (0.07 if age <= 3 else 0.028):
                svc.log_event(sub, "active", "closed", "close", sub.customer)
                sub.status, sub.closed_at, sub.next_billing_date = "closed", me, None
                stats["churned"] += 1
            elif rng.random() < 0.035:
                seats = next((l for l in sub.lines if l.product_id == cat["crm"].id), None)
                if seats:
                    seats.quantity += rng.randint(1, 5)
                    stats["upsells"] += 1

        # 5. Customers pay this month's invoices according to their habits.
        for inv in db.scalars(select(Invoice).where(Invoice.status == "confirmed", Invoice.issue_date >= ms,
                                                    Invoice.issue_date <= me, Invoice.customer_id.in_(profile))).all():
            habit = profile[inv.customer_id]
            if habit == "prompt":
                delay = rng.randint(0, 14)
            elif habit == "slow":
                delay = rng.randint(15, 55)
            else:
                delay = rng.randint(60, 120) if rng.random() < 0.4 else None
            if delay is not None and inv.issue_date + timedelta(days=delay) <= today:
                record_payment(db, inv, inv.balance_due, rng.choice(_METHODS), inv.issue_date + timedelta(days=delay),
                               "Simulated payment", actor)
                stats["payments"] += 1
        db.commit()

    return {**stats, "months": months}
