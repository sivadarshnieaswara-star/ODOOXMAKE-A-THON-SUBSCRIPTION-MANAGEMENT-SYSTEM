import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app.auth import hash_password, validate_password_strength, verify_password
from backend.app.models import EmailLog, User

from .conftest import PASSWORD, login, register


@pytest.mark.parametrize("pw,ok", [
    ("weak", False), ("Short1!", False), ("NoSpecial12", False), ("nouppercase1!", False),
    ("NOLOWERCASE1!", False), ("ValidPass123!", True), ("Abcdefgh#", True),
])
def test_password_policy(pw, ok):
    if ok:
        validate_password_strength(pw)
    else:
        with pytest.raises(HTTPException):
            validate_password_strength(pw)


def test_password_must_be_more_than_eight_characters():
    with pytest.raises(HTTPException):
        validate_password_strength("Abcdef#1")  # exactly 8
    validate_password_strength("Abcdefg#1")  # 9


def test_pbkdf2_hash_uses_unique_salt_and_verifies():
    h1, s1 = hash_password(PASSWORD)
    h2, s2 = hash_password(PASSWORD)
    assert s1 != s2 and h1 != h2
    assert verify_password(PASSWORD, h1, s1)
    assert not verify_password("WrongPass123!", h1, s1)


def test_register_creates_customer_and_rejects_duplicates(client):
    uid, _ = register(client, "new@example.com")
    r = client.post("/api/auth/register", json={"email": "NEW@example.com", "password": PASSWORD, "name": "Dup"})
    assert r.status_code == 400 and "already registered" in r.json()["detail"]
    me = client.get("/api/auth/me", headers=login(client, "new@example.com", PASSWORD)).json()
    assert me["role"] == "customer" and me["id"] == uid


def test_register_rejects_weak_password(client):
    r = client.post("/api/auth/register", json={"email": "weak@example.com", "password": "password", "name": "W"})
    assert r.status_code == 400


def test_login_wrong_password(client, customer):
    r = client.post("/api/auth/login", json={"email": "shop@example.com", "password": "WrongPass123!"})
    assert r.status_code == 401


def test_admin_bootstrap_exists(client, admin):
    assert client.get("/api/auth/me", headers=admin).json()["role"] == "admin"


def test_only_admin_creates_staff(client, admin, staff, customer):
    body = {"email": "x@brightloop.com", "password": PASSWORD, "name": "X"}
    assert client.post("/api/staff", headers=staff, json=body).status_code == 403
    assert client.post("/api/staff", headers=customer[1], json=body).status_code == 403
    weak = client.post("/api/staff", headers=admin, json={**body, "password": "weakpass"})
    assert weak.status_code == 400
    assert client.post("/api/staff", headers=admin, json=body).status_code == 201


def test_only_admin_manages_catalog(client, admin, staff, customer):
    body = {"name": "CRM", "sales_price": 45}
    assert client.post("/api/products", headers=staff, json=body).status_code == 403
    assert client.post("/api/products", headers=customer[1], json=body).status_code == 403
    assert client.post("/api/products", headers=admin, json=body).status_code == 201
    assert client.get("/api/products", headers=staff).status_code == 200
    assert client.post("/api/plans", headers=staff, json={"name": "P", "cost": 1}).status_code == 403
    assert client.post("/api/taxes", headers=staff, json={"name": "T", "rate_percentage": 5}).status_code == 403
    assert client.post("/api/discounts", headers=staff, json={"code": "X1", "value": 5}).status_code == 403


def test_variant_surcharge_effective_price(client, admin):
    p = client.post("/api/products", headers=admin, json={"name": "ERP Cloud", "sales_price": 1200}).json()
    v = client.post(f"/api/products/{p['id']}/variants", headers=admin,
                    json={"attribute_name": "Brand", "variant_value": "Odoo", "surcharge": 560}).json()
    assert v["effective_price"] == 1760


def test_customer_cannot_see_cost_price(client, admin, customer):
    client.post("/api/products", headers=admin, json={"name": "ERP", "sales_price": 100, "cost_price": 40})
    prods = client.get("/api/products", headers=customer[1]).json()
    assert prods[0]["cost_price"] == 0


def _reset_token(db_session):
    with db_session() as s:
        body = s.scalars(select(EmailLog).order_by(EmailLog.id.desc())).first().body
    return re.search(r"reset_token=(\S+)", body).group(1)


def test_password_reset_flow_is_single_use(client, db_session, customer):
    r = client.post("/api/auth/forgot-password", json={"email": "shop@example.com"})
    assert r.status_code == 200
    token = _reset_token(db_session)
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "weak"}).status_code == 400
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "BrandNew#2026"}).status_code == 200
    login(client, "shop@example.com", "BrandNew#2026")
    # replay is rejected
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "Another#2026"}).status_code == 400


def test_forgot_password_does_not_reveal_accounts(client):
    r = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200


def test_expired_reset_token_rejected(client, db_session, customer):
    client.post("/api/auth/forgot-password", json={"email": "shop@example.com"})
    token = _reset_token(db_session)
    with db_session() as s:
        u = s.scalar(select(User).where(User.email == "shop@example.com"))
        u.reset_token_expiry = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        s.commit()
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "BrandNew#2026"}).status_code == 400


def test_disabled_account_cannot_log_in(client, admin, customer):
    uid, _ = customer
    client.patch(f"/api/users/{uid}", headers=admin, json={"is_active": False})
    r = client.post("/api/auth/login", json={"email": "shop@example.com", "password": PASSWORD})
    assert r.status_code == 403
