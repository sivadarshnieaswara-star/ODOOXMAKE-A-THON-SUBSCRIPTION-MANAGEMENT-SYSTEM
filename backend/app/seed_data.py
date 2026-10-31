"""Admin bootstrap (always) and the demo dataset (when the database is empty)."""
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import DiscountRule, Invoice, Plan, Product, ProductVariant, QuotationTemplate, QuotationTemplateLine, \
    TaxRule, User
from .schemas import SubLineIn
from .services import subscription_service as svc
from .services.billing_service import run_billing
from .services.payment_service import record_payment

ADMIN_EMAIL = "admin@brightloop.com"
ADMIN_PASSWORD = "BrightloopAdmin#2026"


def _user(db: Session, email: str, password: str, role: str, name: str, company: str | None = None,
          phone: str | None = None) -> User:
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        return existing
    pw_hash, salt = hash_password(password)
    user = User(email=email, password_hash=pw_hash, password_salt=salt, role=role, name=name,
                company_name=company, phone=phone)
    db.add(user)
    db.flush()
    return user


def bootstrap_admin(db: Session) -> User:
    """A fresh install always has an admin, otherwise nobody could create staff or products."""
    admin = db.scalar(select(User).where(User.role == "admin"))
    if admin is None:
        admin = _user(db, ADMIN_EMAIL, ADMIN_PASSWORD, "admin", "Brightloop Admin", "Brightloop Software")
        db.commit()
    return admin


def seed_demo(db: Session, today: date | None = None) -> None:
    if db.scalar(select(Product.id).limit(1)):
        return  # already has data
    today = today or date.today()
    admin = bootstrap_admin(db)
    _user(db, "staff@brightloop.com", "BrightloopStaff#2026", "staff", "Sam Rivera", "Brightloop Software")
    acme = _user(db, "acme@corp.com", "CustomerPass#2026", "customer", "Priya Natarajan", "Acme Corporation",
                 "+91 98400 11111")
    retail = _user(db, "retail@shop.com", "CustomerPass#2026", "customer", "Arjun Mehta", "Corner Retail Shop",
                   "+91 98400 22222")
    globex = _user(db, "finance@globex.com", "CustomerPass#2026", "customer", "Hank Scorpio", "Globex Industries",
                   "+91 98400 33333")
    initech = _user(db, "bill@initech.com", "CustomerPass#2026", "customer", "Bill Lumbergh", "Initech",
                    "+91 98400 44444")
    umbrella = _user(db, "ops@umbrella.io", "CustomerPass#2026", "customer", "Alice Abernathy", "Umbrella Labs",
                     "+91 98400 55555")

    gst = TaxRule(name="GST 18%", rate_percentage=18.0, is_default=True)
    reduced = TaxRule(name="Reduced GST 5%", rate_percentage=5.0)
    db.add_all([gst, reduced])
    db.flush()

    erp = Product(name="Brightloop ERP Cloud", product_type="software", sales_price=1200, cost_price=310,
                  notes="Core ERP suite, per company instance.")
    erp.variants = [
        ProductVariant(attribute_name="Brand", variant_value="Standard Edition", surcharge=0),
        ProductVariant(attribute_name="Brand", variant_value="Odoo Brand Edition", surcharge=560),
    ]
    crm = Product(name="CRM Pro", product_type="software", sales_price=45, cost_price=8, notes="Priced per seat.")
    analytics = Product(name="Advanced Analytics Add-On", product_type="addon", sales_price=200, cost_price=40)
    backup = Product(name="Daily Cloud Backup", product_type="addon", sales_price=60, cost_price=12)
    onboarding = Product(name="Guided Onboarding", product_type="service", sales_price=500, cost_price=150,
                         tax_rule=reduced)
    db.add_all([erp, crm, analytics, backup, onboarding])

    enterprise = Plan(name="Enterprise Annual Contract", cost=15000, billing_frequency="yearly", min_quantity=5,
                      auto_close_on_expiry=True, allow_early_close=False, allow_pause=False, allow_renewal=True)
    growth = Plan(name="Growth Monthly Plan", cost=500, billing_frequency="monthly", min_quantity=1,
                  auto_close_on_expiry=False, allow_early_close=True, allow_pause=True, allow_renewal=True)
    pilot = Plan(name="Pilot Weekly Trial", cost=50, billing_frequency="weekly", min_quantity=1,
                 start_date=today - relativedelta(months=6), end_date=today + relativedelta(months=6),
                 auto_close_on_expiry=True, allow_early_close=True, allow_pause=False, allow_renewal=False)
    sandbox = Plan(name="Developer Sandbox (Daily)", cost=5, billing_frequency="daily", min_quantity=1,
                   auto_close_on_expiry=True, allow_early_close=True, allow_pause=True, allow_renewal=False)
    db.add_all([enterprise, growth, pilot, sandbox])
    db.flush()
    odoo_variant = erp.variants[1]

    tpl = QuotationTemplate(name="Enterprise ERP Bundle", validity_days=30, contract_months=12, plan=enterprise,
                            payment_terms="net_30", notes="ERP (Odoo brand) + 10 CRM seats + analytics.")
    tpl.lines = [
        # Yearly plan, so line prices are annual (12 x the monthly catalog price).
        QuotationTemplateLine(product_id=erp.id, variant_id=odoo_variant.id, quantity=1, unit_price=1760 * 12),
        QuotationTemplateLine(product_id=crm.id, quantity=10, unit_price=45 * 12),
        QuotationTemplateLine(product_id=analytics.id, quantity=1, unit_price=200 * 12),
    ]
    tpl2 = QuotationTemplate(name="Small Business Starter", validity_days=14, contract_months=12, plan=growth,
                             payment_terms="net_15", notes="CRM seats with daily backup.")
    tpl2.lines = [QuotationTemplateLine(product_id=crm.id, quantity=3),
                  QuotationTemplateLine(product_id=backup.id, quantity=1)]
    db.add_all([tpl, tpl2])

    db.add_all([
        DiscountRule(code="SEATS10", description="10% off CRM Pro when taking 10+ seats",
                     discount_type="percentage", value=10, min_quantity=10, target_type="product",
                     product_id=crm.id, max_uses=100),
        DiscountRule(code="LOYAL250", description="250 off any invoice above 2,000 (limited)",
                     discount_type="fixed", value=250, min_purchase=2000, target_type="subscription",
                     start_date=today - relativedelta(months=3), end_date=today + relativedelta(months=3),
                     max_uses=6),
    ])
    db.flush()

    def make(customer, plan, start, lines, status="active", terms="net_15", months=12, expiry=None):
        sub = svc.create_subscription(
            db, customer_id=customer.id, plan_id=plan.id, start_date=start,
            expiry_date=expiry if expiry is not None else (start + relativedelta(months=months) - timedelta(days=1)
                                                            if months else None),
            payment_terms=terms, notes=None, lines=[SubLineIn(**l) for l in lines], actor=admin)
        path = ["send_quotation", "confirm", "activate"]
        stop = {"draft": 0, "quotation": 1, "confirmed": 2, "active": 3}[status if status in
                                                                          ("draft", "quotation", "confirmed") else "active"]
        for action in path[:stop]:
            svc.transition(db, sub, action, admin, today=start)
        return sub

    # Active book: a mix of frequencies, some starting exactly on a billing boundary so
    # running billing today has work to do.
    make(acme, enterprise, today - relativedelta(months=13), months=24, terms="net_30", lines=[
        dict(product_id=erp.id, variant_id=odoo_variant.id, quantity=1, unit_price=1760 * 12),
        dict(product_id=crm.id, quantity=12, unit_price=45 * 12),
        dict(product_id=analytics.id, quantity=1, unit_price=200 * 12)])
    make(retail, growth, today - relativedelta(months=4), months=0, lines=[
        dict(product_id=crm.id, quantity=3), dict(product_id=backup.id, quantity=1)])
    make(globex, growth, today - relativedelta(months=5), months=0, lines=[
        dict(product_id=erp.id, quantity=1), dict(product_id=crm.id, quantity=5)])
    make(umbrella, pilot, today - timedelta(weeks=8), months=0,
         expiry=today + timedelta(weeks=8), lines=[dict(product_id=crm.id, quantity=2)])
    make(initech, sandbox, today - timedelta(days=10), months=0, lines=[])
    paused = make(umbrella, growth, today - relativedelta(months=2), months=0,
                  lines=[dict(product_id=analytics.id, quantity=1)])

    run_billing(db, as_of=today - timedelta(days=1), auto_confirm=True)

    svc.transition(db, paused, "pause", admin, today=today)
    # Pipeline: work in progress for the sales team.
    quote = svc.create_from_template(db, tpl, initech.id, today + timedelta(days=7), admin)
    svc.transition(db, quote, "send_quotation", admin)
    make(globex, enterprise, today + timedelta(days=14), status="draft", lines=[
        dict(product_id=erp.id, variant_id=erp.variants[0].id, quantity=1, unit_price=1200 * 12),
        dict(product_id=crm.id, quantity=8, unit_price=45 * 12)])
    make(retail, pilot, today - timedelta(weeks=12), months=0, expiry=today - timedelta(weeks=4),
                  lines=[dict(product_id=crm.id, quantity=1)])
    run_billing(db, as_of=today - timedelta(days=1), auto_confirm=True)

    # Money in: most customers pay on time; Globex has fallen behind and Acme paid part of one invoice.
    methods = ["bank_transfer", "card", "upi", "stripe", "cash"]
    invoices = db.scalars(select(Invoice).where(Invoice.status == "confirmed").order_by(Invoice.id)).all()
    acme_partial_done = False
    for n, inv in enumerate(invoices):
        if inv.customer_id == globex.id and inv.due_date < today:
            continue
        if inv.due_date >= today - timedelta(days=3) and inv.customer_id != initech.id:
            continue  # recent invoices still open
        paid_on = min(today, inv.issue_date + timedelta(days=3 + n % 9))
        amount = inv.balance_due
        if inv.customer_id == acme.id and not acme_partial_done:
            amount, acme_partial_done = round(inv.balance_due / 2, 2), True
        record_payment(db, inv, amount, methods[n % len(methods)], paid_on, "Seeded demo payment", admin)
    db.commit()
