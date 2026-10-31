from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, TaxRule


def default_tax_rate(db: Session) -> float:
    rule = db.scalar(select(TaxRule).where(TaxRule.is_default.is_(True), TaxRule.is_active.is_(True)))
    return rule.rate_percentage if rule else 0.0


def tax_rate_for_product(db: Session, product: Product | None) -> float:
    """The product's own tax rule when it has an active one, else the system default."""
    if product is not None and product.tax_rule is not None and product.tax_rule.is_active:
        return product.tax_rule.rate_percentage
    return default_tax_rate(db)


def set_default(db: Session, rule: TaxRule) -> None:
    """Only one default tax rule at a time."""
    if rule.is_default:
        for other in db.scalars(select(TaxRule).where(TaxRule.is_default.is_(True), TaxRule.id != rule.id)):
            other.is_default = False
