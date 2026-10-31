import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import ACCESS_TOKEN_MINUTES, JWT_ALGORITHM, SECRET_KEY
from .database import get_db
from .models import User

PBKDF2_ITERATIONS = 240_000
_SPECIAL = re.compile(r"[^A-Za-z0-9]")


def validate_password_strength(password: str) -> None:
    """More than eight characters, with an uppercase, a lowercase and a special character."""
    problems = []
    if len(password) <= 8:
        problems.append("be more than 8 characters long")
    if not re.search(r"[A-Z]", password):
        problems.append("contain an uppercase letter")
    if not re.search(r"[a-z]", password):
        problems.append("contain a lowercase letter")
    if not _SPECIAL.search(password):
        problems.append("contain a special character")
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must " + ", ".join(problems) + ".")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


def require_customer(user: User = Depends(get_current_user)) -> User:
    if user.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Customer portal only")
    return user


def require_staff(user: User = Depends(get_current_user)) -> User:
    """Internal team: admin or staff."""
    if user.role not in ("admin", "staff"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Staff access required")
    return user
