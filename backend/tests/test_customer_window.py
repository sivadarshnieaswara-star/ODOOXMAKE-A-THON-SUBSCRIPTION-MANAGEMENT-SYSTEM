from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from .conftest import make_active_sub, register


def change(client, admin, product_id, new_price, days=30):
    r = client.post("/api/price-changes", headers=admin, json={
        "product_id": product_id, "new_price": new_price, "effective_on": (date.today() + timedelta(days=days)).isoformat()})
    assert r.status_code == 201, r.text
    return r.json()


def entries(client, headers, sid):
    return [e["event_type"] for e in client.get(f"/api/subscriptions/{sid}/blackbox", headers=headers).json()["entries"]]


# ---------- Price Change Guardian ----------
def test_price_change_notice_guardian_and_apply(client, admin, staff, customer, catalog):
    cid, ch = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"], "quantity": 4}], date.today())
    assert client.post("/api/price-changes", headers=staff, json={"product_id": catalog["seat"]["id"], "new_price": 12,
                                                                  "effective_on": "2099-01-01"}).status_code == 403
    pc = change(client, admin, catalog["seat"]["id"], 12)
    assert pc["subscriptions"] == 1 and pc["status"] == "scheduled"
    assert any("Price update" in e["subject"] for e in client.get("/api/emails", headers=admin).json())
    assert "price_change_notice" in entries(client, ch, sub["id"])

    g = client.get("/api/portal/guardian", headers=ch).json()
    c = g["changes"][0]
    assert (c["old_unit"], c["new_unit"], c["per_period"], c["change_pct"]) == (10.0, 12.0, 8.0, 20.0)
    assert g["status"] == "attention" and g["yearly_exposure"] == 96.0 and c["lock_would_save"] > 0

    # nothing changes until the effective date, then billing applies it
    eff = date.today() + timedelta(days=30)
    client.post("/api/billing/run", headers=staff, json={"as_of": (eff - timedelta(days=1)).isoformat()})
    assert client.get(f"/api/subscriptions/{sub['id']}", headers=staff).json()["lines"][0]["unit_price"] == 10.0
    client.post("/api/billing/run", headers=staff, json={"as_of": eff.isoformat()})
    assert client.get(f"/api/subscriptions/{sub['id']}", headers=staff).json()["lines"][0]["unit_price"] == 12.0
    assert client.get(f"/api/products/{catalog['seat']['id']}", headers=admin).json()["sales_price"] == 12.0
    assert "price_changed" in entries(client, staff, sub["id"])
    assert client.get("/api/portal/guardian", headers=ch).json()["changes"] == []


def test_cancelled_price_change_never_applies(client, admin, staff, customer, catalog):
    cid, ch = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"]}], date.today())
    pc = change(client, admin, catalog["seat"]["id"], 15, days=5)
    assert client.post("/api/price-changes", headers=admin, json={"product_id": catalog["seat"]["id"], "new_price": 20,
                       "effective_on": (date.today() + timedelta(days=9)).isoformat()}).status_code == 400   # one at a time
    assert client.post(f"/api/price-changes/{pc['id']}/cancel", headers=admin).json()["status"] == "cancelled"
    client.post("/api/billing/run", headers=staff, json={"as_of": (date.today() + timedelta(days=10)).isoformat()})
    assert client.get(f"/api/subscriptions/{sub['id']}", headers=staff).json()["lines"][0]["unit_price"] == 10.0
    assert client.get("/api/portal/guardian", headers=ch).json()["changes"] == []


# ---------- Renewal Lock ----------
def test_renewal_lock_defers_price_change_and_commits_customer(client, admin, staff, customer, catalog):
    cid, ch = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"], "quantity": 2}], date.today())
    change(client, admin, catalog["seat"]["id"], 11)
    locked = client.post(f"/api/subscriptions/{sub['id']}/renewal-lock", headers=ch).json()
    until = date.fromisoformat(locked["price_lock_until"])
    assert until == date.today() + relativedelta(months=12) - timedelta(days=1)
    assert "close" not in locked["allowed_actions"]
    assert client.post(f"/api/subscriptions/{sub['id']}/actions/close", headers=ch).status_code == 400
    assert client.post(f"/api/subscriptions/{sub['id']}/renewal-lock", headers=ch).status_code == 400  # already locked

    g = client.get("/api/portal/guardian", headers=ch).json()
    assert g["status"] == "protected" and g["changes"][0]["deferred_by_lock"] is True
    assert g["changes"][0]["your_effective_on"] == (until + timedelta(days=1)).isoformat()

    # the change date passes: the locked subscription keeps its price
    client.post("/api/billing/run", headers=staff, json={"as_of": (date.today() + timedelta(days=40)).isoformat()})
    assert client.get(f"/api/subscriptions/{sub['id']}", headers=staff).json()["lines"][0]["unit_price"] == 10.0
    # staff can release the lock; the deferred change then applies on the next run
    assert client.delete(f"/api/subscriptions/{sub['id']}/renewal-lock", headers=ch).status_code == 403
    client.delete(f"/api/subscriptions/{sub['id']}/renewal-lock", headers=staff)
    client.post("/api/billing/run", headers=staff, json={"as_of": (date.today() + timedelta(days=41)).isoformat()})
    assert client.get(f"/api/subscriptions/{sub['id']}", headers=staff).json()["lines"][0]["unit_price"] == 11.0
    assert {"renewal_locked", "renewal_unlocked", "price_changed"} <= set(entries(client, staff, sub["id"]))


def test_lock_on_fixed_term_covers_next_renewal(client, staff, customer, catalog):
    cid, ch = customer
    expiry = date.today() + timedelta(days=100)
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today(), expiry)
    locked = client.post(f"/api/subscriptions/{sub['id']}/renewal-lock", headers=ch).json()
    assert locked["price_lock_until"] == (expiry + relativedelta(months=12)).isoformat()


# ---------- Timeline ----------
def test_personal_timeline_past_and_future(client, admin, staff, customer, catalog):
    cid, ch = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"], "quantity": 3}],
                          date.today() - timedelta(days=5))
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    change(client, admin, catalog["seat"]["id"], 20, days=45)
    t = client.get("/api/portal/timeline", headers=ch).json()
    past = [i for i in t["items"] if not i["future"]]
    future = [i for i in t["items"] if i["future"]]
    assert {"created", "activated", "invoice_issued"} <= {i["kind"] for i in past}
    due = [i for i in future if i["kind"] == "invoice_due"]
    assert len(due) >= 5 and due[0]["amount"] == 33.0                     # 3 x 10 + 10% tax
    assert any(i["kind"] == "price_change" for i in future)
    assert any(i["amount"] == 66.0 for i in due)                          # after the change: 3 x 20 + tax
    assert t["next_payment"]["date"] == due[0]["date"]
    _, other = register(client, "other@example.com")
    assert client.get("/api/portal/timeline", headers=other).json()["items"] == []
    assert client.get("/api/portal/timeline", headers=staff).status_code == 403


# ---------- QR Pass ----------
def test_qr_pass_verifies_and_can_be_revoked(client, staff, customer, catalog):
    cid, ch = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today())
    p = client.get(f"/api/subscriptions/{sub['id']}/pass", headers=ch).json()
    assert p["state"] == "valid" and p["qr_svg"].startswith("<svg") and p["token"] in p["verify_url"]
    v = client.get(f"/api/pass/{p['token']}").json()                     # public, no login
    assert v["ok"] is True and v["holder"] == "Small Shop" and "amount" not in str(v)
    page = client.get(f"/pass/{p['token']}")
    assert page.status_code == 200 and "Valid subscription" in page.text

    # forged and revoked codes fail
    assert client.get(f"/api/pass/{p['token'][:-2]}xx").json()["ok"] is False
    new = client.post(f"/api/subscriptions/{sub['id']}/pass/regenerate", headers=ch).json()
    assert new["version"] == 2
    old = client.get(f"/api/pass/{p['token']}").json()
    assert old["ok"] is False and "replaced" in old["message"]
    assert client.get(f"/api/pass/{new['token']}").json()["ok"] is True

    # status follows the subscription
    client.post(f"/api/subscriptions/{sub['id']}/actions/pause", headers=staff)
    assert client.get(f"/api/pass/{new['token']}").json()["state"] == "paused"
    _, other = register(client, "nosy@example.com")
    assert client.get(f"/api/subscriptions/{sub['id']}/pass", headers=other).status_code == 404
