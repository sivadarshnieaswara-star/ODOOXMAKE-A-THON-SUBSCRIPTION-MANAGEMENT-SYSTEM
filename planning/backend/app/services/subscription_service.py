from datetime import date, timedelta
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from ..models import (
    Subscription, SubscriptionLine, SubscriptionStatus,
    Plan, QuotationTemplate, Product, ProductVariant
)
from .tax_service import TaxService

class SubscriptionService:
    @staticmethod
    def generate_subscription_number(db: Session) -> str:
        """Generates next sequential subscription number like SUB-00001."""
        count = db.query(Subscription).count() + 1
        return f"SUB-{count:05d}"

    @classmethod
    def create_from_template(
        cls,
        db: Session,
        customer_id: int,
        template_id: int,
        start_date: Optional[date] = None,
        payment_terms: str = "Net 15"
    ) -> Subscription:
        """Instantiates a subscription starting from a Quotation Template."""
        template = db.query(QuotationTemplate).filter(QuotationTemplate.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Quotation template not found.")

        if not template.plan_id:
            raise HTTPException(status_code=400, detail="Quotation template has no assigned plan.")

        plan = db.query(Plan).filter(Plan.id == template.plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Assigned plan not found.")

        today = start_date or date.today()
        expiry_date = today + timedelta(days=template.validity_days)

        sub_number = cls.generate_subscription_number(db)
        subscription = Subscription(
            subscription_number=sub_number,
            customer_id=customer_id,
            plan_id=plan.id,
            start_date=today,
            expiry_date=expiry_date,
            payment_terms=payment_terms,
            status=SubscriptionStatus.DRAFT,
            next_billing_date=today,
            notes=f"Created from template: {template.name}"
        )
        db.add(subscription)
        db.flush()

        default_tax = TaxService.get_default_tax_rate(db)
        for tline in template.lines:
            line_amount = round(tline.quantity * tline.unit_price, 2)
            s_line = SubscriptionLine(
                subscription_id=subscription.id,
                product_id=tline.product_id,
                variant_id=tline.variant_id,
                quantity=tline.quantity,
                unit_price=tline.unit_price,
                tax_rate=default_tax,
                amount=line_amount
            )
            db.add(s_line)

        db.commit()
        db.refresh(subscription)
        return subscription

    @classmethod
    def transition_status(
        cls,
        db: Session,
        subscription: Subscription,
        target_status: str,
        user_role: str = "staff"
    ) -> Subscription:
        """
        Validates and transitions subscription through its lifecycle states:
        Draft -> Quotation -> Confirmed -> Active -> Closed (or Paused).
        Enforces plan-level policy flags (can_pause, can_close_early, can_renew).
        """
        target = target_status.lower()
        current = subscription.status.lower()
        plan = subscription.plan

        # Valid transitions mapping
        valid_transitions = {
            SubscriptionStatus.DRAFT: [SubscriptionStatus.QUOTATION, SubscriptionStatus.CONFIRMED, SubscriptionStatus.CLOSED],
            SubscriptionStatus.QUOTATION: [SubscriptionStatus.CONFIRMED, SubscriptionStatus.DRAFT, SubscriptionStatus.CLOSED],
            SubscriptionStatus.CONFIRMED: [SubscriptionStatus.ACTIVE, SubscriptionStatus.CLOSED],
            SubscriptionStatus.ACTIVE: [SubscriptionStatus.PAUSED, SubscriptionStatus.CLOSED],
            SubscriptionStatus.PAUSED: [SubscriptionStatus.ACTIVE, SubscriptionStatus.CLOSED],
            SubscriptionStatus.CLOSED: [SubscriptionStatus.DRAFT, SubscriptionStatus.QUOTATION]  # Renewal
        }

        allowed_targets = valid_transitions.get(current, [])
        if target not in allowed_targets:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot transition subscription from '{current}' to '{target}'. Allowed: {allowed_targets}"
            )

        # Policy checks
        if target == SubscriptionStatus.PAUSED:
            if plan and not plan.allow_pause:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Plan '{plan.name}' does not allow pausing."
                )

        if target == SubscriptionStatus.CLOSED and current == SubscriptionStatus.ACTIVE:
            today = date.today()
            is_early = subscription.expiry_date and subscription.expiry_date > today
            if is_early and plan and not plan.allow_early_close:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Plan '{plan.name}' does not allow early closure."
                )

        if current == SubscriptionStatus.CLOSED and target in [SubscriptionStatus.DRAFT, SubscriptionStatus.QUOTATION]:
            if plan and not plan.allow_renewal:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Plan '{plan.name}' does not allow renewal."
                )

        subscription.status = target
        db.commit()
        db.refresh(subscription)
        return subscription
