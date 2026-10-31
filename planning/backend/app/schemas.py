from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field

# User Schemas
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: str
    company_name: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

class StaffCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "staff"

class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    company_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

# Product & Variant Schemas
class VariantCreate(BaseModel):
    attribute_name: str = "Brand"
    variant_value: str
    surcharge: float = 0.0

class VariantResponse(BaseModel):
    id: int
    attribute_name: str
    variant_value: str
    surcharge: float
    is_active: bool

    class Config:
        from_attributes = True

class ProductCreate(BaseModel):
    name: str
    product_type: str = "software"
    sales_price: float
    cost_price: float = 0.0
    notes: Optional[str] = None
    variants: List[VariantCreate] = []

class ProductResponse(BaseModel):
    id: int
    name: str
    product_type: str
    sales_price: float
    cost_price: float
    notes: Optional[str]
    is_active: bool
    variants: List[VariantResponse] = []

    class Config:
        from_attributes = True

# Plan Schemas
class PlanCreate(BaseModel):
    name: str
    cost: float
    billing_frequency: str = "monthly"  # daily, weekly, monthly, yearly
    min_quantity: int = 1
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    auto_close_on_expiry: bool = True
    allow_early_close: bool = True
    allow_pause: bool = True
    allow_renewal: bool = True

class PlanResponse(BaseModel):
    id: int
    name: str
    cost: float
    billing_frequency: str
    min_quantity: int
    start_date: Optional[date]
    end_date: Optional[date]
    auto_close_on_expiry: bool
    allow_early_close: bool
    allow_pause: bool
    allow_renewal: bool
    is_active: bool

    class Config:
        from_attributes = True

# Quotation Template Schemas
class TemplateLineCreate(BaseModel):
    product_id: int
    variant_id: Optional[int] = None
    quantity: int = 1
    unit_price: float

class TemplateCreate(BaseModel):
    name: str
    validity_days: int = 15
    plan_id: Optional[int] = None
    notes: Optional[str] = None
    lines: List[TemplateLineCreate] = []

class TemplateLineResponse(BaseModel):
    id: int
    product_id: int
    product_name: Optional[str] = None
    variant_id: Optional[int] = None
    variant_name: Optional[str] = None
    quantity: int
    unit_price: float

    class Config:
        from_attributes = True

class TemplateResponse(BaseModel):
    id: int
    name: str
    validity_days: int
    plan_id: Optional[int]
    plan_name: Optional[str] = None
    notes: Optional[str]
    lines: List[TemplateLineResponse] = []

    class Config:
        from_attributes = True

# Subscription Schemas
class SubscriptionLineCreate(BaseModel):
    product_id: int
    variant_id: Optional[int] = None
    quantity: int = 1
    unit_price: float
    tax_rate: float = 0.0

class SubscriptionCreate(BaseModel):
    customer_id: Optional[int] = None  # Admin/staff can specify; for customers, derived from JWT
    plan_id: int
    start_date: Optional[date] = None
    expiry_date: Optional[date] = None
    payment_terms: str = "Net 15"
    template_id: Optional[int] = None
    lines: List[SubscriptionLineCreate] = []
    notes: Optional[str] = None

class SubscriptionLineResponse(BaseModel):
    id: int
    product_id: int
    product_name: Optional[str] = None
    variant_id: Optional[int] = None
    variant_name: Optional[str] = None
    quantity: int
    unit_price: float
    tax_rate: float
    amount: float

    class Config:
        from_attributes = True

class SubscriptionResponse(BaseModel):
    id: int
    subscription_number: str
    customer_id: int
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    plan_id: int
    plan_name: Optional[str] = None
    billing_frequency: Optional[str] = None
    start_date: date
    expiry_date: Optional[date]
    payment_terms: str
    status: str
    last_billing_date: Optional[date]
    next_billing_date: Optional[date]
    notes: Optional[str]
    total_recurring_amount: Optional[float] = 0.0
    lines: List[SubscriptionLineResponse] = []
    created_at: datetime

    class Config:
        from_attributes = True

class SubscriptionStatusUpdate(BaseModel):
    status: str  # draft, quotation, confirmed, active, paused, closed
    notes: Optional[str] = None

# Tax Rule Schemas
class TaxRuleCreate(BaseModel):
    name: str
    rate_percentage: float
    is_default: bool = False

class TaxRuleResponse(BaseModel):
    id: int
    name: str
    rate_percentage: float
    is_default: bool
    is_active: bool

    class Config:
        from_attributes = True

# Discount Rule Schemas
class DiscountRuleCreate(BaseModel):
    code: str
    description: str
    discount_type: str = "percentage"  # percentage, fixed
    value: float
    min_purchase: float = 0.0
    min_quantity: int = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    max_uses: Optional[int] = None
    target_type: str = "subscription"  # subscription, product
    product_id: Optional[int] = None

class DiscountRuleResponse(BaseModel):
    id: int
    code: str
    description: str
    discount_type: str
    value: float
    min_purchase: float
    min_quantity: int
    start_date: Optional[date]
    end_date: Optional[date]
    max_uses: Optional[int]
    current_uses: int
    target_type: str
    product_id: Optional[int]
    is_active: bool

    class Config:
        from_attributes = True

# Invoice Schemas
class InvoiceLineResponse(BaseModel):
    id: int
    product_name: str
    variant_name: Optional[str]
    quantity: int
    unit_price: float
    tax_rate: float
    line_subtotal: float
    line_tax: float
    line_total: float

    class Config:
        from_attributes = True

class InvoiceResponse(BaseModel):
    id: int
    invoice_number: str
    subscription_id: Optional[int]
    customer_id: int
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    issue_date: date
    due_date: date
    status: str
    subtotal: float
    discount_amount: float
    discount_code: Optional[str]
    tax_amount: float
    total_amount: float
    balance_due: float
    is_overdue: bool = False
    sent_at: Optional[datetime]
    notes: Optional[str]
    lines: List[InvoiceLineResponse] = []
    created_at: datetime

    class Config:
        from_attributes = True

class InvoiceStatusUpdate(BaseModel):
    status: str  # confirmed, cancelled

# Payment Schemas
class PaymentCreate(BaseModel):
    invoice_id: int
    amount: float
    payment_method: str = "credit_card"  # bank_transfer, credit_card, cash, upi, stripe
    payment_date: Optional[date] = None
    note: Optional[str] = None

class PaymentResponse(BaseModel):
    id: int
    payment_number: str
    invoice_id: int
    invoice_number: Optional[str] = None
    customer_id: int
    customer_name: Optional[str] = None
    amount: float
    payment_method: str
    payment_date: date
    note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

# Analytics / Financial Summary Schemas
class FinancialOverview(BaseModel):
    active_subscriptions_count: int
    mrr: float
    arr: float
    total_revenue_collected: float
    total_outstanding_amount: float
    overdue_invoices_count: int
    overdue_amount: float
    response_time_ms: float
