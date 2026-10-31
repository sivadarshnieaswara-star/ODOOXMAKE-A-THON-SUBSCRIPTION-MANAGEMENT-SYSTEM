from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["admin", "staff", "customer"]
ProductType = Literal["software", "addon", "service"]
Frequency = Literal["daily", "weekly", "monthly", "yearly"]
PaymentTerms = Literal["immediate", "net_7", "net_15", "net_30", "net_45"]
PaymentMethod = Literal["bank_transfer", "card", "cash", "upi", "stripe"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth / users ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str = Field(min_length=1, max_length=120)
    company_name: str | None = None
    phone: str | None = None

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.strip().lower()


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


PROFILE_FIELDS = ("name", "company_name", "phone", "job_title", "billing_email", "website", "industry", "company_size",
                  "tax_id", "address_line1", "address_line2", "city", "state", "postal_code", "country",
                  "preferred_payment_method", "notify_offers")


class UserOut(ORM):
    id: int
    email: str
    role: str
    name: str
    company_name: str | None
    phone: str | None
    is_active: bool
    created_at: datetime
    job_title: str | None = None
    billing_email: str | None = None
    website: str | None = None
    industry: str | None = None
    company_size: str | None = None
    tax_id: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    preferred_payment_method: str | None = None
    notify_offers: bool | None = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class StaffIn(RegisterIn):
    pass


class UserUpdate(BaseModel):
    """Partial update: only the fields sent are changed, and sending null clears a field."""
    name: str | None = Field(default=None, min_length=1, max_length=120)
    company_name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None
    job_title: str | None = Field(default=None, max_length=120)
    billing_email: EmailStr | None = None
    website: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=80)
    company_size: Literal["1-10", "11-50", "51-200", "201-1000", "1000+"] | None = None
    tax_id: str | None = Field(default=None, max_length=30)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=80)
    preferred_payment_method: PaymentMethod | None = None
    notify_offers: bool | None = None

    @field_validator("tax_id")
    @classmethod
    def clean_tax_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper().replace(" ", "")
        if not v.isalnum():
            raise ValueError("Tax ID can only contain letters and numbers")
        if len(v) == 15 and not (v[:2].isdigit() and v[2:7].isalpha()):
            raise ValueError("That doesn't look like a valid GSTIN (e.g. 33ABCDE1234F1Z5)")
        return v

    @field_validator("website")
    @classmethod
    def clean_website(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if v and "." not in v:
            raise ValueError("Enter a website like example.com")
        return v if v.startswith(("http://", "https://")) else f"https://{v}"

    @field_validator("billing_email")
    @classmethod
    def lower_billing_email(cls, v):
        return v.lower() if v else v


# ---------- Taxes ----------
class TaxIn(BaseModel):
    name: str
    rate_percentage: float = Field(ge=0, le=100)
    is_default: bool = False
    is_active: bool = True


class TaxOut(ORM, TaxIn):
    id: int


# ---------- Products ----------
class VariantIn(BaseModel):
    attribute_name: str = Field(min_length=1)
    variant_value: str = Field(min_length=1)
    surcharge: float = Field(default=0.0, ge=0)
    is_active: bool = True


class VariantOut(ORM, VariantIn):
    id: int
    product_id: int
    effective_price: float


class ProductIn(BaseModel):
    name: str = Field(min_length=1)
    product_type: ProductType = "software"
    sales_price: float = Field(ge=0)
    cost_price: float = Field(default=0.0, ge=0)
    notes: str | None = None
    tax_rule_id: int | None = None
    is_active: bool = True


class ProductOut(ORM, ProductIn):
    id: int
    created_at: datetime
    variants: list[VariantOut] = []


# ---------- Plans ----------
class PlanIn(BaseModel):
    name: str = Field(min_length=1)
    cost: float = Field(ge=0)
    billing_frequency: Frequency = "monthly"
    min_quantity: int = Field(default=1, ge=1)
    start_date: date | None = None
    end_date: date | None = None
    auto_close_on_expiry: bool = True
    allow_early_close: bool = True
    allow_pause: bool = False
    allow_renewal: bool = True
    max_pause_days: int | None = Field(default=None, ge=1, le=365)
    is_active: bool = True


class PlanOut(ORM, PlanIn):
    id: int


# ---------- Quotation templates ----------
class TemplateLineIn(BaseModel):
    product_id: int
    variant_id: int | None = None
    quantity: int = Field(default=1, ge=1)
    unit_price: float | None = Field(default=None, ge=0)


class TemplateLineOut(ORM, TemplateLineIn):
    id: int
    product_name: str
    variant_label: str | None


class TemplateIn(BaseModel):
    name: str = Field(min_length=1)
    validity_days: int = Field(default=30, ge=1)
    contract_months: int = Field(default=12, ge=1)
    plan_id: int
    payment_terms: PaymentTerms = "net_30"
    notes: str | None = None
    lines: list[TemplateLineIn] = []


class TemplateOut(ORM):
    id: int
    name: str
    validity_days: int
    contract_months: int
    plan_id: int
    plan_name: str
    payment_terms: str
    notes: str | None
    lines: list[TemplateLineOut]


class TemplateUseIn(BaseModel):
    customer_id: int
    start_date: date | None = None


# ---------- Subscriptions ----------
class SubLineIn(BaseModel):
    product_id: int
    variant_id: int | None = None
    quantity: int = Field(default=1, ge=1)
    unit_price: float | None = Field(default=None, ge=0)


class SubLineOut(ORM):
    id: int
    product_id: int
    product_name: str
    variant_id: int | None
    variant_label: str | None
    quantity: int
    unit_price: float
    tax_rate: float
    amount: float
    tax_amount: float


class SubscriptionIn(BaseModel):
    customer_id: int
    plan_id: int
    start_date: date
    expiry_date: date | None = None
    payment_terms: PaymentTerms = "net_30"
    notes: str | None = None
    lines: list[SubLineIn] = []


class SubscriptionUpdate(BaseModel):
    start_date: date | None = None
    expiry_date: date | None = None
    payment_terms: PaymentTerms | None = None
    notes: str | None = None
    lines: list[SubLineIn] | None = None


class SubEventOut(ORM):
    from_status: str | None
    to_status: str
    action: str
    actor_email: str | None
    created_at: datetime


class SubscriptionOut(ORM):
    id: int
    subscription_number: str
    customer_id: int
    customer_name: str
    customer_email: str
    plan_id: int
    plan_name: str
    billing_frequency: str
    start_date: date
    expiry_date: date | None
    payment_terms: str
    status: str
    quotation_valid_until: date | None
    paused_at: date | None = None
    resume_on: date | None = None
    pause_reason: str | None = None
    max_pause_days: int | None = None
    price_lock_until: date | None = None
    price_locked_at: date | None = None
    last_billing_date: date | None
    next_billing_date: date | None
    notes: str | None
    recurring_amount: float
    allowed_actions: list[str]
    lines: list[SubLineOut] = []
    events: list[SubEventOut] = []


class SubActionIn(BaseModel):
    """Optional details for an action; only pause uses them today."""
    resume_on: date | None = None
    reason: str | None = Field(default=None, max_length=255)


class PortalSubscribeIn(BaseModel):
    plan_id: int
    product_id: int
    variant_id: int | None = None
    quantity: int = Field(default=1, ge=1)


# ---------- Discounts ----------
class DiscountIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    description: str | None = None
    discount_type: Literal["percentage", "fixed"] = "percentage"
    value: float = Field(gt=0)
    min_purchase: float = Field(default=0.0, ge=0)
    min_quantity: int = Field(default=0, ge=0)
    start_date: date | None = None
    end_date: date | None = None
    max_uses: int | None = Field(default=None, ge=1)
    target_type: Literal["subscription", "product"] = "subscription"
    product_id: int | None = None
    subscription_id: int | None = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def upper_code(cls, v: str) -> str:
        return v.strip().upper()


class DiscountOut(ORM, DiscountIn):
    id: int
    current_uses: int


# ---------- Invoices ----------
class InvoiceLineOut(ORM):
    product_name: str
    variant_name: str | None
    quantity: int
    unit_price: float
    tax_rate: float
    line_subtotal: float
    line_discount: float
    line_tax: float
    line_total: float


class PaymentOut(ORM):
    id: int
    payment_number: str
    invoice_id: int
    invoice_number: str
    customer_id: int
    customer_name: str
    amount: float
    payment_method: str
    payment_date: date
    note: str | None
    recorded_by: str | None


class InvoiceOut(ORM):
    id: int
    invoice_number: str
    subscription_id: int
    subscription_number: str
    customer_id: int
    customer_name: str
    customer_address: list[str] = []
    customer_tax_id: str | None = None
    customer_email: str
    period_start: date
    period_end: date
    issue_date: date
    due_date: date
    status: str
    subtotal: float
    discount_amount: float
    discount_code: str | None
    tax_amount: float
    total_amount: float
    balance_due: float
    is_overdue: bool
    days_overdue: int
    sent_at: datetime | None
    paid_at: date | None
    notes: str | None
    lines: list[InvoiceLineOut] = []
    payments: list[PaymentOut] = []


class BillingRunIn(BaseModel):
    as_of: date | None = None
    auto_confirm: bool = False


class BillingRunOut(BaseModel):
    as_of: date
    subscriptions_scanned: int
    invoices_created: int
    invoice_numbers: list[str]
    subscriptions_closed: int
    skipped_existing: int
    subscriptions_resumed: int = 0


# ---------- Payments ----------
class PaymentIn(BaseModel):
    invoice_id: int
    amount: float = Field(gt=0)
    payment_method: PaymentMethod
    payment_date: date | None = None
    note: str | None = None


class PortalPayIn(BaseModel):
    payment_method: PaymentMethod = "card"


# ---------- Email ----------
class EmailOut(ORM):
    id: int
    to_email: str
    subject: str
    body: str
    delivered: bool
    created_at: datetime


class EmailSendTestIn(BaseModel):
    to_email: EmailStr
    subject: str = "Brightloop System Test Email"
    body: str = "This is an automated test notification from the Brightloop Subscription Management System."
