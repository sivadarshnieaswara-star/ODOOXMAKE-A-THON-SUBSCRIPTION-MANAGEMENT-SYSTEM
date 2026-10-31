#!/usr/bin/env python3
"""Brightloop Subscription Management System — Database Builder & Initializer.

Usage:
    python build_db.py                         # Build schema, ensure admin, seed demo if empty
    python build_db.py --seed                  # Force re-seed of demo dataset
    python build_db.py --email user@domain.com # Seed/update dummy customers to route to your email
    python build_db.py --reset                 # Drop and recreate everything fresh
"""

import argparse
import sys
from datetime import date
from sqlalchemy import func, select

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from backend.app import config
from backend.app.database import Base, SessionLocal, add_missing_columns, engine, init_db
from backend.app.models import (
    BlackBoxEntry,
    DiscountRule,
    EmailLog,
    Invoice,
    Payment,
    Plan,
    Product,
    Subscription,
    SystemSetting,
    TaxRule,
    User,
)
from backend.app.seed_data import ADMIN_EMAIL, ADMIN_PASSWORD, bootstrap_admin, seed_demo
from backend.app.services.blackbox import backfill_missing
from backend.app.services.mail_service import set_mail_setting


def build_database(reset: bool = False, force_seed: bool = False, target_email: str | None = None):
    print("=" * 65)
    print(">>  Brightloop Database Builder")
    print(f"    Target Database: {config.DATABASE_URL}")
    if target_email:
        print(f"    Target Demo Mail : {target_email}")
    print("=" * 65)

    if reset:
        print("\n[RESET] Dropping all existing tables...")
        Base.metadata.drop_all(engine)
        print("[OK] All tables dropped successfully.")

    print("\n[1/4] Constructing database schema and tables...")
    Base.metadata.create_all(engine)
    print("[OK] Schema initialized.")

    print("\n[2/4] Verifying and applying forward schema migrations...")
    migrated_columns = add_missing_columns(engine)
    if migrated_columns:
        print(f"[OK] Columns migrated: {', '.join(migrated_columns)}")
    else:
        print("[OK] Schema is up to date (no migrations required).")

    with SessionLocal() as db:
        print("\n[3/4] Ensuring Platform Administrator bootstrap...")
        admin = bootstrap_admin(db)
        print(f"[OK] Admin verified: {admin.email} (Role: {admin.role})")

        product_count = db.scalar(select(func.count(Product.id)))
        if product_count == 0 or force_seed:
            print("\n[4/4] Seeding demonstration dataset (Products, Plans, Customers, Subscriptions)...")
            seed_demo(db, today=date.today())
            print("[OK] Demonstration dataset populated successfully.")
        else:
            print("\n[4/4] Database already contains records; skipping demo seed.")

        # Update dummy customers to use target_email if specified
        if target_email:
            print(f"\n📧 Setting Target Mail in Settings & Customer Accounts: {target_email}")
            set_mail_setting(db, "mail_target_email", target_email)
            set_mail_setting(db, "mail_redirect_dummy", "true")
            updated = 0
            for cust in db.scalars(select(User).where(User.role == "customer")).all():
                cust.billing_email = target_email
                updated += 1
            print(f"[OK] Updated {updated} customer accounts to route billing to {target_email}")

        # Reconstruct / ensure blackbox records
        print("\n[*] Finalizing Cryptographic Blackbox Flight Recorder audit chain...")
        backfill_missing(db)
        db.commit()

        # Database statistics summary
        print("\n" + "=" * 65)
        print("DATABASE BUILD SUMMARY & METRICS")
        print("=" * 65)
        counts = {
            "Users (Admin/Staff/Customers)": db.scalar(select(func.count(User.id))),
            "Products & Services": db.scalar(select(func.count(Product.id))),
            "Recurring Billing Plans": db.scalar(select(func.count(Plan.id))),
            "Active & Pipeline Subscriptions": db.scalar(select(func.count(Subscription.id))),
            "Generated Invoices": db.scalar(select(func.count(Invoice.id))),
            "Recorded Payments": db.scalar(select(func.count(Payment.id))),
            "Tax & Discount Rules": db.scalar(select(func.count(TaxRule.id))) + db.scalar(select(func.count(DiscountRule.id))),
            "Blackbox Audit Events": db.scalar(select(func.count(BlackBoxEntry.id))),
            "Outbox Email Records": db.scalar(select(func.count(EmailLog.id))),
        }
        for label, val in counts.items():
            print(f"  * {label:<35} : {val:>4}")
        print("=" * 65)
        print("\n[SUCCESS] Database is healthy, fully migrated, and ready for operations!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Brightloop Database Builder & Seeder")
    parser.add_argument("--reset", action="store_true", help="Drop all tables and recreate from scratch")
    parser.add_argument("--seed", action="store_true", help="Force re-seed demo data")
    parser.add_argument("--email", type=str, default=None, help="Target email address for demo customer routing")
    args = parser.parse_args()

    try:
        build_database(reset=args.reset, force_seed=args.seed, target_email=args.email)
    except Exception as e:
        print(f"\n[ERROR] Database build error: {e}", file=sys.stderr)
        raise
