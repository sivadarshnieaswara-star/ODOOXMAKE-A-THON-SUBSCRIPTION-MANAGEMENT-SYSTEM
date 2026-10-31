import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'brightloop.db'}")


def _load_secret_key() -> str:
    """Use SECRET_KEY from the environment, else a key persisted next to the project
    so issued tokens survive restarts during development."""
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_urlsafe(48)
    key_file.write_text(key)
    return key


SECRET_KEY = _load_secret_key()
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "480"))
RESET_TOKEN_MINUTES = 60

# Base URL used when building links in outgoing emails (password reset).
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")

# Optional real SMTP delivery. When SMTP_HOST is unset, emails are only written
# to the outbox table (visible to admins) and the server log.
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM", "billing@brightloop.com")

SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "1") == "1"
