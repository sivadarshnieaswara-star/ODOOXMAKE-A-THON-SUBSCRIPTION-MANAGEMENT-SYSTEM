import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    create_access_token, get_current_user, hash_password, hash_token, validate_password_strength, verify_password,
)
from ..config import APP_BASE_URL, RESET_TOKEN_MINUTES
from ..database import get_db
from ..models import User
from ..schemas import (
    ChangePasswordIn, ForgotPasswordIn, LoginIn, RegisterIn, ResetPasswordIn, TokenOut, UserOut, UserUpdate,
)
from ..services.common import send_email

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_user(db: Session, data: RegisterIn, role: str) -> User:
    validate_password_strength(data.password)
    email = data.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(400, "Email already registered")
    pw_hash, salt = hash_password(data.password)
    user = User(email=email, password_hash=pw_hash, password_salt=salt, role=role, name=data.name,
                company_name=data.company_name, phone=data.phone)
    db.add(user)
    db.flush()
    return user


@router.post("/register", response_model=TokenOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    """Public sign-up always creates a customer account."""
    user = create_user(db, data, "customer")
    db.commit()
    return TokenOut(access_token=create_access_token(user), user=user)


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash, user.password_salt):
        raise HTTPException(401, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(403, "This account has been disabled")
    return TokenOut(access_token=create_access_token(user), user=user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(data: UserUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for field in ("name", "company_name", "phone"):
        if getattr(data, field) is not None:
            setattr(user, field, getattr(data, field))
    db.commit()
    return user


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordIn, db: Session = Depends(get_db)):
    """Email a one-time reset link. Same response whether or not the email exists."""
    user = db.scalar(select(User).where(User.email == data.email.lower(), User.is_active.is_(True)))
    if user:
        token = secrets.token_urlsafe(32)
        user.reset_token_hash = hash_token(token)
        user.reset_token_expiry = _now() + timedelta(minutes=RESET_TOKEN_MINUTES)
        link = f"{APP_BASE_URL}/?reset_token={token}"
        send_email(db, user.email, "Reset your Brightloop password",
                   f"Hello {user.name},\n\nUse this link to set a new password. It expires in "
                   f"{RESET_TOKEN_MINUTES} minutes and works once:\n\n{link}\n\n"
                   "If you did not ask for this, you can ignore this email.")
        db.commit()
    return {"message": "If that email is registered, a reset link has been sent to it."}


@router.post("/reset-password")
def reset_password(data: ResetPasswordIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.reset_token_hash == hash_token(data.token)))
    if user is None or user.reset_token_expiry is None or user.reset_token_expiry < _now():
        raise HTTPException(400, "Reset link is invalid or has expired")
    validate_password_strength(data.new_password)
    user.password_hash, user.password_salt = hash_password(data.new_password)
    user.reset_token_hash = user.reset_token_expiry = None  # single use
    db.commit()
    return {"message": "Password updated. You can now sign in."}


@router.post("/change-password")
def change_password(data: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash, user.password_salt):
        raise HTTPException(400, "Current password is incorrect")
    validate_password_strength(data.new_password)
    user.password_hash, user.password_salt = hash_password(data.new_password)
    db.commit()
    return {"message": "Password changed"}
