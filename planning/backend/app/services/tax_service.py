from sqlalchemy.orm import Session
from ..models import TaxRule

class TaxService:
    @staticmethod
    def get_default_tax_rate(db: Session) -> float:
        """Retrieves the default active tax rate percentage or falls back to 0.0."""
        tax = db.query(TaxRule).filter(TaxRule.is_active == True, TaxRule.is_default == True).first()
        if not tax:
            tax = db.query(TaxRule).filter(TaxRule.is_active == True).first()
        return tax.rate_percentage if tax else 0.0

    @staticmethod
    def compute_tax(amount: float, rate_percentage: float) -> float:
        """Calculates tax amount rounded to 2 decimal places."""
        return round((amount * rate_percentage) / 100.0, 2)
