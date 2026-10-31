from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import Product, ProductVariant, TaxRule, User
from ..schemas import ProductIn, ProductOut, VariantIn, VariantOut

router = APIRouter(prefix="/api", tags=["products"])


def _get(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


def _check_tax(db: Session, tax_rule_id: int | None):
    if tax_rule_id is not None and db.get(TaxRule, tax_rule_id) is None:
        raise HTTPException(400, "Tax rule not found")


@router.get("/products", response_model=list[ProductOut])
def list_products(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Product).options(selectinload(Product.variants)).order_by(Product.name)
    if user.role == "customer":
        stmt = stmt.where(Product.is_active.is_(True))
    products = db.scalars(stmt).all()
    if user.role == "customer":  # customers never see cost prices or inactive variants
        return [ProductOut.model_validate(p).model_copy(update={
            "cost_price": 0.0, "notes": None,
            "variants": [VariantOut.model_validate(v) for v in p.variants if v.is_active]}) for p in products]
    return products


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get(db, product_id)


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(data: ProductIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _check_tax(db, data.tax_rule_id)
    product = Product(**data.model_dump())
    db.add(product)
    db.commit()
    return product


@router.put("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, data: ProductIn, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    product = _get(db, product_id)
    _check_tax(db, data.tax_rule_id)
    for k, v in data.model_dump().items():
        setattr(product, k, v)
    db.commit()
    return product


@router.delete("/products/{product_id}", status_code=204)
def archive_product(product_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Archive rather than delete, so existing subscriptions and invoices keep their history."""
    _get(db, product_id).is_active = False
    db.commit()


@router.post("/products/{product_id}/variants", response_model=VariantOut, status_code=201)
def add_variant(product_id: int, data: VariantIn, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    product = _get(db, product_id)
    variant = ProductVariant(**data.model_dump())
    product.variants.append(variant)
    db.commit()
    return variant


@router.put("/variants/{variant_id}", response_model=VariantOut)
def update_variant(variant_id: int, data: VariantIn, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    variant = db.get(ProductVariant, variant_id)
    if variant is None:
        raise HTTPException(404, "Variant not found")
    for k, v in data.model_dump().items():
        setattr(variant, k, v)
    db.commit()
    return variant


@router.delete("/variants/{variant_id}", status_code=204)
def archive_variant(variant_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    variant = db.get(ProductVariant, variant_id)
    if variant is None:
        raise HTTPException(404, "Variant not found")
    variant.is_active = False
    db.commit()
