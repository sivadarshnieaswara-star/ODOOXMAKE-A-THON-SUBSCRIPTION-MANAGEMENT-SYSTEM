from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Enumerations kept as plain strings so SQLite stays simple; validated in schemas.
ROLES = ("admin", "staff", "customer")
PRODUCT_TYPES = ("software", "addon", "service")
FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
SUB_STATES = ("draft", "quotation", "confirmed", "active", "paused", "closed")
INVOICE_STATES = ("draft", "confirmed", "paid", "cancelled")
PAYMENT_METHODS = ("bank_transfer", "card", "cash", "upi", "stripe")
PAYMENT_TERMS = {"immediate": 0, "net_7": 7, "net_15": 15, "net_30": 30, "net_45": 45}


class Counter(Base):
    """Named sequence counters for SUB-/INV-/PAY- numbers."""
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    password_salt: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(20), default="customer", index=True)
    name: Mapped[str] = mapped_column(String(120))
    company_name: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(40))
    # Customer profile
    job_title: Mapped[str | None] = mapped_column(String(120))
    billing_email: Mapped[str | None] = mapped_column(String(255))   # invoices go here when set
    website: Mapped[str | None] = mapped_column(String(255))
    industry: Mapped[str | None] = mapped_column(String(80))
    company_size: Mapped[str | None] = mapped_column(String(20))
    tax_id: Mapped[str | None] = mapped_column(String(30))           # GSTIN / VAT number
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(80))
    preferred_payment_method: Mapped[str | None] = mapped_column(String(20))
    notify_offers: Mapped[bool | None] = mapped_column(Boolean, default=True)  # offers & product news (billing mail always goes)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    reset_token_hash: Mapped[str | None] = mapped_column(String(128))
    reset_token_expiry: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def billing_to(self) -> str:
        """Where invoices, receipts and reminders are sent."""
        return self.billing_email or self.email

    @property
    def address_lines(self) -> list[str]:
        city = " ".join(x for x in (self.city, self.postal_code) if x)
        return [x for x in (self.address_line1, self.address_line2, ", ".join(x for x in (city, self.state) if x), self.country) if x]


class TaxRule(Base):
    __tablename__ = "tax_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    rate_percentage: Mapped[float] = mapped_column(Float)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    product_type: Mapped[str] = mapped_column(String(20), default="software")
    sales_price: Mapped[float] = mapped_column(Float, default=0.0)
    cost_price: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text)
    tax_rule_id: Mapped[int | None] = mapped_column(ForeignKey("tax_rules.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    tax_rule: Mapped[TaxRule | None] = relationship()


class ProductVariant(Base):
    __tablename__ = "product_variants"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    attribute_name: Mapped[str] = mapped_column(String(80))
    variant_value: Mapped[str] = mapped_column(String(120))
    surcharge: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[Product] = relationship(back_populates="variants")

    @property
    def effective_price(self) -> float:
        return round(self.product.sales_price + self.surcharge, 2)

    @property
    def label(self) -> str:
        return f"{self.attribute_name}: {self.variant_value}"


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    billing_frequency: Mapped[str] = mapped_column(String(10), default="monthly")
    min_quantity: Mapped[int] = mapped_column(Integer, default=1)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    auto_close_on_expiry: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_early_close: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_pause: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_renewal: Mapped[bool] = mapped_column(Boolean, default=True)
    max_pause_days: Mapped[int | None] = mapped_column(Integer)  # None = no limit
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class QuotationTemplate(Base):
    __tablename__ = "quotation_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    validity_days: Mapped[int] = mapped_column(Integer, default=30)
    contract_months: Mapped[int] = mapped_column(Integer, default=12)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    payment_terms: Mapped[str] = mapped_column(String(20), default="net_30")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    plan: Mapped[Plan] = relationship()
    lines: Mapped[list["QuotationTemplateLine"]] = relationship(back_populates="template", cascade="all, delete-orphan")


class QuotationTemplateLine(Base):
    __tablename__ = "quotation_template_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("quotation_templates.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float | None] = mapped_column(Float)  # None = use catalog price

    template: Mapped[QuotationTemplate] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    variant: Mapped[ProductVariant | None] = relationship()


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_sub_status_next", "status", "next_billing_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    term_start: Mapped[date | None] = mapped_column(Date)  # start of the current contract term (moves on renewal)
    payment_terms: Mapped[str] = mapped_column(String(20), default="net_30")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    quotation_valid_until: Mapped[date | None] = mapped_column(Date)
    last_billing_date: Mapped[date | None] = mapped_column(Date)
    next_billing_date: Mapped[date | None] = mapped_column(Date)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("quotation_templates.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[date | None] = mapped_column(Date)
    paused_at: Mapped[date | None] = mapped_column(Date)
    resume_on: Mapped[date | None] = mapped_column(Date, index=True)  # automatic resume date while paused
    pause_reason: Mapped[str | None] = mapped_column(String(255))
    price_lock_until: Mapped[date | None] = mapped_column(Date)   # Renewal Lock: prices frozen (and no early exit) until this date
    price_locked_at: Mapped[date | None] = mapped_column(Date)
    pass_version: Mapped[int | None] = mapped_column(Integer)     # bumping it revokes previously issued QR passes

    customer: Mapped[User] = relationship()
    plan: Mapped[Plan] = relationship()
    lines: Mapped[list["SubscriptionLine"]] = relationship(back_populates="subscription", cascade="all, delete-orphan")
    events: Mapped[list["SubscriptionEvent"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan", order_by="SubscriptionEvent.id")

    @property
    def recurring_amount(self) -> float:
        """Untaxed amount billed each period: the lines, or the plan cost when there are none."""
        if self.lines:
            return round(sum(l.amount for l in self.lines), 2)
        return round(self.plan.cost, 2)


class SubscriptionLine(Base):
    __tablename__ = "subscription_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0)

    subscription: Mapped[Subscription] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    variant: Mapped[ProductVariant | None] = relationship()

    @property
    def amount(self) -> float:
        return round(self.quantity * self.unit_price, 2)

    @property
    def tax_amount(self) -> float:
        return round(self.amount * self.tax_rate / 100.0, 2)


class SubscriptionEvent(Base):
    """Audit trail of state changes so anyone on the team can see where a subscription stands."""
    __tablename__ = "subscription_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(40))
    actor_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    subscription: Mapped[Subscription] = relationship(back_populates="events")


class DiscountRule(Base):
    __tablename__ = "discount_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(String(255))
    discount_type: Mapped[str] = mapped_column(String(20), default="percentage")  # percentage | fixed
    value: Mapped[float] = mapped_column(Float)
    min_purchase: Mapped[float] = mapped_column(Float, default=0.0)
    min_quantity: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    max_uses: Mapped[int | None] = mapped_column(Integer)  # None = unlimited
    current_uses: Mapped[int] = mapped_column(Integer, default=0)
    target_type: Mapped[str] = mapped_column(String(20), default="subscription")  # subscription | product
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"))  # None = any
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # Idempotency guarantee: one invoice per subscription per billing period.
        UniqueConstraint("subscription_id", "period_start", name="uq_invoice_sub_period"),
        Index("ix_inv_status_due", "status", "due_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    issue_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    discount_code: Mapped[str | None] = mapped_column(String(40))
    discount_rule_id: Mapped[int | None] = mapped_column(ForeignKey("discount_rules.id"))
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    balance_due: Mapped[float] = mapped_column(Float, default=0.0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    paid_at: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    subscription: Mapped[Subscription] = relationship()
    customer: Mapped[User] = relationship()
    lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", order_by="Payment.id")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    product_name: Mapped[str] = mapped_column(String(160))
    variant_name: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    line_subtotal: Mapped[float] = mapped_column(Float)
    line_discount: Mapped[float] = mapped_column(Float, default=0.0)
    line_tax: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    payment_method: Mapped[str] = mapped_column(String(20))
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    invoice: Mapped[Invoice] = relationship(back_populates="payments")
    customer: Mapped[User] = relationship()


class PriceChange(Base):
    """A scheduled catalog price change. Existing subscribers get notice and the new price from effective_on."""
    __tablename__ = "price_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    old_price: Mapped[float] = mapped_column(Float)
    new_price: Mapped[float] = mapped_column(Float)
    announced_on: Mapped[date] = mapped_column(Date)
    effective_on: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | applied | cancelled
    created_by: Mapped[str | None] = mapped_column(String(255))

    product: Mapped[Product] = relationship()
    notices: Mapped[list["PriceNotice"]] = relationship(back_populates="change", cascade="all, delete-orphan")


class PriceNotice(Base):
    """One subscription line affected by a price change: the customer-facing notice and its own effective date."""
    __tablename__ = "price_notices"
    id: Mapped[int] = mapped_column(primary_key=True)
    price_change_id: Mapped[int] = mapped_column(ForeignKey("price_changes.id"), index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("subscription_lines.id"))
    old_unit: Mapped[float] = mapped_column(Float)
    new_unit: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)
    effective_on: Mapped[date] = mapped_column(Date, index=True)   # later than the change itself if a Renewal Lock defers it
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | applied | cancelled

    change: Mapped[PriceChange] = relationship(back_populates="notices")
    subscription: Mapped[Subscription] = relationship()
    line: Mapped[SubscriptionLine] = relationship()


class BlackBoxEntry(Base):
    """Append-only, hash-chained record of every important billing event on one subscription.
    hash = sha256(prev_hash + this entry's fields), so editing any past entry breaks the chain."""
    __tablename__ = "blackbox_entries"
    __table_args__ = (UniqueConstraint("subscription_id", "seq", name="uq_blackbox_seq"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    occurred_on: Mapped[date] = mapped_column(Date)          # business date of the event
    recorded_at: Mapped[datetime] = mapped_column(DateTime)  # wall-clock time it was written
    event_type: Mapped[str] = mapped_column(String(40))
    actor_email: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(String(500))
    amount: Mapped[float | None] = mapped_column(Float)
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    internal: Mapped[bool] = mapped_column(Boolean, default=False)  # hidden from the customer copy
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class AutomationLog(Base):
    """What the recommendations engine (or someone acting on it) did, for the activity feed."""
    __tablename__ = "automation_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(String(500))
    actor_email: Mapped[str | None] = mapped_column(String(255))
    autopilot: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RecommendationDismissal(Base):
    __tablename__ = "recommendation_dismissals"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    until: Mapped[date] = mapped_column(Date)


class EmailLog(Base):
    """Outbox of every email the system sends (reset links, invoices)."""
    __tablename__ = "email_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    to_email: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SystemSetting(Base):
    """Dynamic configuration settings stored in the database."""
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
