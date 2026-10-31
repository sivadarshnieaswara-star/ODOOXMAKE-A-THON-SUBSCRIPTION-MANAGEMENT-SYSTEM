from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import DiscountRule


@dataclass
class DraftLine:
    product_id: int | None
    quantity: int
    subtotal: float


@dataclass
class DiscountResult:
    rule: DiscountRule
    amount: float
    per_line: list[float]  # discount allocated to each draft line, same order


def usable_rules(db: Session, on: date) -> list[DiscountRule]:
    """Active rules inside their date window that have not run out of uses."""
    return list(db.scalars(
        select(DiscountRule).where(
            DiscountRule.is_active.is_(True),
            or_(DiscountRule.start_date.is_(None), DiscountRule.start_date <= on),
            or_(DiscountRule.end_date.is_(None), DiscountRule.end_date >= on),
            or_(DiscountRule.max_uses.is_(None), DiscountRule.current_uses < DiscountRule.max_uses),
        )
    ))


def _evaluate(rule: DiscountRule, subscription_id: int, lines: list[DraftLine]) -> DiscountResult | None:
    if rule.target_type == "product":
        idx = [i for i, l in enumerate(lines) if l.product_id == rule.product_id]
    else:
        if rule.subscription_id is not None and rule.subscription_id != subscription_id:
            return None
        idx = list(range(len(lines)))
    base = round(sum(lines[i].subtotal for i in idx), 2)
    qty = sum(lines[i].quantity for i in idx)
    if not idx or base <= 0 or base < rule.min_purchase or qty < rule.min_quantity:
        return None
    amount = base * rule.value / 100.0 if rule.discount_type == "percentage" else min(rule.value, base)
    amount = round(min(amount, base), 2)
    if amount <= 0:
        return None
    # Spread the discount over the qualifying lines in proportion to their subtotal; the last
    # line takes the rounding remainder so the parts always add up to the total.
    per_line = [0.0] * len(lines)
    remaining = amount
    for n, i in enumerate(idx):
        share = remaining if n == len(idx) - 1 else round(amount * lines[i].subtotal / base, 2)
        per_line[i] = share
        remaining = round(remaining - share, 2)
    return DiscountResult(rule=rule, amount=amount, per_line=per_line)


def best_discount(db: Session, subscription_id: int, lines: list[DraftLine], on: date) -> DiscountResult | None:
    """One discount per invoice: the applicable rule that saves the customer the most."""
    results = [r for rule in usable_rules(db, on) if (r := _evaluate(rule, subscription_id, lines))]
    return max(results, key=lambda r: r.amount, default=None)
