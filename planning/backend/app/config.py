import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = os.path.join(BASE_DIR, "brightloop_subscriptions.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "brightloop-super-secure-secret-key-2026-hackathon")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

COMPANY_NAME = "Brightloop Software"
COMPANY_EMAIL = "billing@brightloop.com"
COMPANY_PHONE = "+1 (800) 555-0199"
COMPANY_ADDRESS = "100 Innovation Parkway, Suite 400, Tech City, TC 94016"
