from datetime import date, timedelta

from backend.app.models import Subscription

from .conftest import make_active_sub, register


def test_plan_frequencies_and_policy_flags(client, admin):
    for freq in ("daily", "weekly", "monthly", "yearly"):
        r = client.post("/api/plans", headers=admin, json={
            "name": f"P-{freq}", "cost": 10, "billing_frequency": freq, "min_quantity": 2,
            "start_date": "2026-01-01", "end_date": "2026-12-31", "auto_close_on_expiry": False,
            "allow_early_close": False, "allow_pause": True, "allow_renewal": False})
        assert r.status_code == 201
        p = r.json()
        assert (p["billing_frequency"], p["min_quantity"], p["allow_pause"], p["allow_renewal"]) == (freq, 2, True, False)
    bad = client.post("/api/plans", headers=admin, json={"name": "x", "cost": 1, "billing_frequency": "hourly"})
    assert bad.status_code == 422


def test_template_creates_prefilled_quote(client, staff, customer, catalog):
    cid, _ = customer
    t = client.post("/api/templates", headers=staff, json={
        "name": "Bundle", "plan_id": catalog["plan"]["id"], "validity_days": 15, "contract_months": 12,
        "lines": [{"product_id": catalog["product"]["id"], "variant_id": catalog["variant"]["id"], "quantity": 2},
                  {"product_id": catalog["seat"]["id"], "quantity": 5, "unit_price": 8}]}).json()
    start = date.today()
    sub = client.post(f"/api/templates/{t['id']}/use", headers=staff, json={"customer_id": cid}).json()
    assert sub["status"] == "draft"
    assert sub["subscription_number"] == "SUB-00001"
    assert sub["quotation_valid_until"] == (start + timedelta(days=15)).isoformat()
    assert sub["expiry_date"] == (date(start.year + 1, start.month, start.day) - timedelta(days=1)).isoformat()
    prices = sorted((l["quantity"], l["unit_price"]) for l in sub["lines"])
    assert prices == [(2, 660.0), (5, 8.0)]  # variant price 100 + 560, override 8
    assert sub["recurring_amount"] == 2 * 660 + 40


def test_sequential_numbers(client, staff, customer, catalog):
    cid, _ = customer
    nums = [client.post("/api/subscriptions", headers=staff, json={
        "customer_id": cid, "plan_id": catalog["plan"]["id"], "start_date": date.today().isoformat()}).json()["subscription_number"]
        for _ in range(3)]
    assert nums == ["SUB-00001", "SUB-00002", "SUB-00003"]


def test_full_lifecycle_and_history(client, staff, customer, catalog):
    cid, _ = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"]}], date.today())
    assert sub["status"] == "active" and sub["next_billing_date"] == date.today().isoformat()
    sid = sub["id"]
    r = client.post(f"/api/subscriptions/{sid}/actions/close", headers=staff).json()
    assert r["status"] == "closed"
    assert [e["action"] for e in r["events"]] == ["create", "send_quotation", "confirm", "activate", "close"]


def test_invalid_transitions_rejected(client, staff, customer, catalog):
    cid, _ = customer
    sid = client.post("/api/subscriptions", headers=staff, json={
        "customer_id": cid, "plan_id": catalog["plan"]["id"], "start_date": date.today().isoformat()}).json()["id"]
    assert client.post(f"/api/subscriptions/{sid}/actions/activate", headers=staff).status_code == 400
    assert client.post(f"/api/subscriptions/{sid}/actions/confirm", headers=staff).status_code == 400
    assert client.post(f"/api/subscriptions/{sid}/actions/fly", headers=staff).status_code == 400


def test_plan_policies_enforced(client, admin, staff, customer, catalog):
    cid, _ = customer
    strict = client.post("/api/plans", headers=admin, json={
        "name": "Strict", "cost": 10, "allow_pause": False, "allow_early_close": False, "allow_renewal": False}).json()
    sub = make_active_sub(client, staff, cid, strict["id"], [], date.today(), date.today() + timedelta(days=365))
    sid = sub["id"]
    assert sub["allowed_actions"] == []
    for action in ("pause", "close", "renew"):
        r = client.post(f"/api/subscriptions/{sid}/actions/{action}", headers=staff)
        assert r.status_code == 400, action


def test_pause_resume_and_renew(client, staff, customer, catalog):
    cid, _ = customer
    start = date(2026, 1, 1)
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], start, date(2026, 12, 31))
    sid = sub["id"]
    assert client.post(f"/api/subscriptions/{sid}/actions/pause", headers=staff).json()["status"] == "paused"
    resumed = client.post(f"/api/subscriptions/{sid}/actions/resume", headers=staff).json()
    assert resumed["status"] == "active" and resumed["next_billing_date"] >= date.today().isoformat()
    renewed = client.post(f"/api/subscriptions/{sid}/actions/renew", headers=staff).json()
    assert renewed["expiry_date"] == "2027-12-31"
    again = client.post(f"/api/subscriptions/{sid}/actions/renew", headers=staff).json()
    assert again["expiry_date"] == "2028-12-31"  # each renewal adds one term, not the accumulated length


def test_minimum_quantity_enforced_on_confirm(client, admin, staff, customer, catalog):
    cid, _ = customer
    plan = client.post("/api/plans", headers=admin, json={"name": "Team", "cost": 10, "min_quantity": 5}).json()
    sid = client.post("/api/subscriptions", headers=staff, json={
        "customer_id": cid, "plan_id": plan["id"], "start_date": date.today().isoformat(),
        "lines": [{"product_id": catalog["seat"]["id"], "quantity": 3}]}).json()["id"]
    client.post(f"/api/subscriptions/{sid}/actions/send_quotation", headers=staff)
    r = client.post(f"/api/subscriptions/{sid}/actions/confirm", headers=staff)
    assert r.status_code == 400 and "minimum quantity" in r.json()["detail"]


def test_plan_availability_window(client, admin, staff, customer):
    cid, _ = customer
    plan = client.post("/api/plans", headers=admin, json={
        "name": "Promo", "cost": 5, "start_date": "2026-03-01", "end_date": "2026-03-31"}).json()
    r = client.post("/api/subscriptions", headers=staff, json={"customer_id": cid, "plan_id": plan["id"], "start_date": "2026-04-02"})
    assert r.status_code == 400


def test_expired_quotation_cannot_be_confirmed(client, db_session, staff, customer, catalog):
    cid, _ = customer
    sid = client.post("/api/subscriptions", headers=staff, json={
        "customer_id": cid, "plan_id": catalog["plan"]["id"], "start_date": date.today().isoformat()}).json()["id"]
    client.post(f"/api/subscriptions/{sid}/actions/send_quotation", headers=staff)
    with db_session() as s:
        s.get(Subscription, sid).quotation_valid_until = date.today() - timedelta(days=1)
        s.commit()
    assert client.post(f"/api/subscriptions/{sid}/actions/confirm", headers=staff).status_code == 400


def test_customers_see_only_their_own(client, staff, customer, catalog):
    cid, ch = customer
    other_id, oh = register(client, "other@example.com")
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today())
    assert client.get(f"/api/subscriptions/{sub['id']}", headers=oh).status_code == 404
    assert client.get("/api/subscriptions", headers=oh).json()["total"] == 0
    assert client.get("/api/subscriptions", headers=ch).json()["total"] == 1
    # customers cannot create subscriptions for others or activate
    assert client.post("/api/subscriptions", headers=ch, json={
        "customer_id": cid, "plan_id": catalog["plan"]["id"], "start_date": date.today().isoformat()}).status_code == 403


def test_customer_accepts_quotation_and_self_pauses(client, staff, customer, catalog):
    cid, ch = customer
    sid = client.post("/api/subscriptions", headers=staff, json={
        "customer_id": cid, "plan_id": catalog["plan"]["id"], "start_date": date.today().isoformat()}).json()["id"]
    client.post(f"/api/subscriptions/{sid}/actions/send_quotation", headers=staff)
    assert client.post(f"/api/subscriptions/{sid}/actions/confirm", headers=ch).json()["status"] == "confirmed"
    assert client.post(f"/api/subscriptions/{sid}/actions/activate", headers=ch).status_code == 403
    client.post(f"/api/subscriptions/{sid}/actions/activate", headers=staff)
    assert client.post(f"/api/subscriptions/{sid}/actions/pause", headers=ch).json()["status"] == "paused"


def test_portal_self_subscribe(client, customer, catalog):
    cid, ch = customer
    r = client.post("/api/portal/subscribe", headers=ch, json={
        "plan_id": catalog["plan"]["id"], "product_id": catalog["product"]["id"], "variant_id": catalog["variant"]["id"]})
    assert r.status_code == 201
    s = r.json()
    assert s["status"] == "active" and s["customer_id"] == cid and s["lines"][0]["unit_price"] == 660
