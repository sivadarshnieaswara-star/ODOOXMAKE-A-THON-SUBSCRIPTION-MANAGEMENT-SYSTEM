from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db, make_engine
from backend.app.main import app
from backend.app.seed_data import ADMIN_EMAIL, ADMIN_PASSWORD, bootstrap_admin

PASSWORD = "ValidPass123!"


@pytest.fixture()
def db_session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as s:
        bootstrap_admin(s)
    yield Session
    engine.dispose()


@pytest.fixture()
def client(db_session):
    def override():
        db = db_session()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override
    c = TestClient(app)  # not used as a context manager: skips the demo-data lifespan
    yield c
    app.dependency_overrides.clear()


def login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return login(client, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture()
def staff(client, admin):
    r = client.post("/api/staff", headers=admin, json={"email": "rep@brightloop.com", "password": PASSWORD, "name": "Rep"})
    assert r.status_code == 201, r.text
    return login(client, "rep@brightloop.com", PASSWORD)


def register(client, email, name="Customer", company=None):
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD, "name": name, "company_name": company})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture()
def customer(client):
    return register(client, "shop@example.com", "Shop Owner", "Small Shop")


@pytest.fixture()
def catalog(client, admin):
    """Default 10% tax, a product with an Odoo-brand variant (+560) and a monthly plan."""
    tax = client.post("/api/taxes", headers=admin, json={"name": "VAT 10%", "rate_percentage": 10, "is_default": True}).json()
    prod = client.post("/api/products", headers=admin, json={"name": "ERP", "sales_price": 100, "cost_price": 30}).json()
    var = client.post(f"/api/products/{prod['id']}/variants", headers=admin,
                      json={"attribute_name": "Brand", "variant_value": "Odoo", "surcharge": 560}).json()
    seat = client.post("/api/products", headers=admin, json={"name": "Seat", "sales_price": 10}).json()
    plan = client.post("/api/plans", headers=admin, json={
        "name": "Monthly", "cost": 100, "billing_frequency": "monthly", "allow_pause": True}).json()
    return {"tax": tax, "product": prod, "variant": var, "seat": seat, "plan": plan}


def make_active_sub(client, headers, customer_id, plan_id, lines, start: date, expiry: date | None = None,
                    terms="net_30"):
    body = {"customer_id": customer_id, "plan_id": plan_id, "start_date": start.isoformat(), "payment_terms": terms,
            "lines": lines}
    if expiry:
        body["expiry_date"] = expiry.isoformat()
    r = client.post("/api/subscriptions", headers=headers, json=body)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    for action in ("send_quotation", "confirm", "activate"):
        r = client.post(f"/api/subscriptions/{sid}/actions/{action}", headers=headers)
        assert r.status_code == 200, r.text
    return r.json()
