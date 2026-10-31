from datetime import date
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from ..models import DiscountRule, DiscountType, DiscountTarget, Subscription

class DiscountService:
    @staticmethod
    def evaluate_best_discount(
        db: Session,
        subscription: Subscription,
        subtotal: float,
        total_quantity: int,
        evaluation_date: Optional[date] = None
    ) -> Tuple[Optional[DiscountRule], float]:
        """
        Evaluates active discount rules applicable to the subscription or its products,
        respecting date ranges, minimum purchase/quantity thresholds, and max usage counts.
        Returns the matching rule with the greatest discount and the discount amount.
        """
        if evaluation_date is None:
            evaluation_date = date.today()

        # Query active rules that are within valid date window and haven't exceeded max_uses
        query = db.query(DiscountRule).filter(
            DiscountRule.is_active == True,
            (DiscountRule.start_date == None) | (DiscountRule.start_date <= evaluation_date),
            (DiscountRule.end_date == None) | (DiscountRule.end_date >= evaluation_date)
        )
        rules = query.all()

        best_rule = None
        max_discount = 0.0

        # Collect product ids and quantities present in the subscription
        subscription_product_ids = {line.product_id for line in subscription.lines}
        product_quantities = {}
        product_subtotals = {}
        for line in subscription.lines:
            product_quantities[line.product_id] = product_quantities.get(line.product_id, 0) + line.quantity
            line_cost = line.quantity * line.unit_price
            product_subtotals[line.product_id] = product_subtotals.get(line.product_id, 0.0) + line_cost

        for rule in rules:
            # Check max usage
            if rule.max_uses is not None and rule.current_uses >= rule.max_uses:
                continue

            discount_candidate = 0.0

            if rule.target_type == DiscountTarget.SUBSCRIPTION:
                # Whole subscription discount
                if rule.min_purchase and subtotal < rule.min_purchase:
                    continue
                if rule.min_quantity and total_quantity < rule.min_quantity:
                    continue

                if rule.discount_type == DiscountType.PERCENTAGE:
                    discount_candidate = (subtotal * rule.value) / 100.0
                elif rule.discount_type == DiscountType.FIXED:
                    discount_candidate = min(rule.value, subtotal)

            elif rule.target_type == DiscountTarget.PRODUCT:
                # Specific product discount
                if rule.product_id not in subscription_product_ids:
                    continue

                prod_qty = product_quantities.get(rule.product_id, 0)
                prod_subtotal = product_subtotals.get(rule.product_id, 0.0)

                if rule.min_quantity and prod_qty < rule.min_quantity:
                    continue
                if rule.min_purchase and prod_subtotal < rule.min_purchase:
                    continue

                if rule.discount_type == DiscountType.PERCENTAGE:
                    discount_candidate = (prod_subtotal * rule.value) / 100.0
                elif rule.discount_type == DiscountType.FIXED:
                    discount_candidate = min(rule.value, prod_subtotal)

            discount_candidate = round(discount_candidate, 2)
            if discount_candidate > max_discount:
                max_discount = discount_candidate
                best_rule = rule

        return best_rule, max_discount

    @staticmethod
    def consume_discount(db: Session, rule: DiscountRule) -> None:
        """Increments usage counter and deactivates rule if max limit is reached."""
        rule.current_uses += 1
        if rule.max_uses is not None and rule.current_uses >= rule.max_uses:
            rule.is_active = False
        db.commit()
