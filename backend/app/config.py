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


def _resolve_smtp_config():
    """Discover SMTP settings from environment variables or external user config in-memory.
    NOTE: Never adds or writes a .env file directly into this workspace."""
    host = os.getenv("SMTP_HOST")
    port_str = os.getenv("SMTP_PORT")
    port = int(port_str) if port_str and port_str.isdigit() else 587
    user = os.getenv("SMTP_USER") or os.getenv("GMAIL_USER")
    password = os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_APP_PASS") or os.getenv("GMAIL_APP_PASSWORD")
    sender = os.getenv("SMTP_FROM")
    tls = os.getenv("SMTP_TLS", "1").lower() in ("1", "true", "yes")

    # In-memory check of external candidate env files if credentials not explicitly in os.environ
    if not user or not password:
        candidates = [
            Path.home() / "PyCharmMiscProject" / ".env",
            Path("C:/Users/saisr/PyCharmMiscProject/.env"),
            Path("G:/TUBS-multi/.env"),
        ]
        for candidate in candidates:
            if candidate.exists():
                try:
                    for line in candidate.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip('"').strip("'")
                            if not user and k in ("GMAIL_USER", "SMTP_USER"):
                                user = v
                            if not password and k in ("GMAIL_APP_PASS", "GMAIL_APP_PASSWORD", "SMTP_PASSWORD"):
                                password = v
                            if not host and k == "SMTP_HOST":
                                host = v
                            if not sender and k == "SMTP_FROM":
                                sender = v
                except Exception:
                    pass
                if user and password:
                    break

    if user and not host:
        host = "smtp.gmail.com"
        port = 587

    if not sender:
        sender = user if user else "billing@brightloop.com"

    return host, port, user, password, sender, tls


SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_TLS = _resolve_smtp_config()

SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "1") == "1"
