from datetime import date, timedelta

from .conftest import make_active_sub


def run(client, headers, as_of, auto_confirm=False):
    r = client.post("/api/billing/run", headers=headers, json={"as_of": as_of.isoformat(), "auto_confirm": auto_confirm})
    assert r.status_code == 200, r.text
    return r.json()


def invoices(client, headers, **params):
    return client.get("/api/invoices", headers=headers, params={"limit": 500, **params}).json()["items"]


def test_billing_creates_invoice_with_lines_and_tax(client, staff, customer, catalog):
    cid, _ = customer
    start = date(2026, 1, 15)
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [
        {"product_id": catalog["product"]["id"], "variant_id": catalog["variant"]["id"], "quantity": 1},
        {"product_id": catalog["seat"]["id"], "quantity": 4}], start)
    r = run(client, staff, start)
    assert r["invoices_created"] == 1 and r["invoice_numbers"] == ["INV-00001"]
    inv = client.get("/api/invoices/1", headers=staff).json()
    assert inv["status"] == "draft"
    assert inv["subtotal"] == 700.0 and inv["tax_amount"] == 70.0 and inv["total_amount"] == 770.0
    assert inv["period_start"] == "2026-01-15" and inv["period_end"] == "2026-02-14"
    assert inv["due_date"] == "2026-02-14"  # net 30
    assert {l["product_name"] for l in inv["lines"]} == {"ERP", "Seat"}


def test_billing_is_idempotent(client, staff, customer, catalog):
    cid, _ = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 1))
    first = run(client, staff, date(2026, 3, 1))
    assert first["invoices_created"] == 3  # Jan, Feb, Mar caught up
    second = run(client, staff, date(2026, 3, 1))
    assert second["invoices_created"] == 0
    assert len(invoices(client, staff)) == 3


def test_catch_up_never_skips_a_period(client, staff, customer, catalog, admin):
    cid, _ = customer
    weekly = client.post("/api/plans", headers=admin, json={"name": "W", "cost": 7, "billing_frequency": "weekly"}).json()
    make_active_sub(client, staff, cid, weekly["id"], [], date(2026, 1, 1))
    run(client, staff, date(2026, 1, 20))
    run(client, staff, date(2026, 2, 3))
    starts = sorted(i["period_start"] for i in invoices(client, staff))
    assert starts == ["2026-01-01", "2026-01-08", "2026-01-15", "2026-01-22", "2026-01-29"]


def test_monthly_dates_do_not_drift(client, staff, customer, catalog):
    cid, _ = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 31))
    run(client, staff, date(2026, 4, 30))
    starts = sorted(i["period_start"] for i in invoices(client, staff))
    assert starts == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]


def test_billing_stops_at_expiry_and_auto_closes(client, staff, customer, catalog):
    cid, _ = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 1), date(2026, 3, 15))
    r = run(client, staff, date(2026, 6, 1))
    assert r["invoices_created"] == 3 and r["subscriptions_closed"] == 1
    last = max(invoices(client, staff), key=lambda i: i["period_start"])
    assert last["period_end"] == "2026-03-15"  # final period is cut at the expiry date
    sub = client.get("/api/subscriptions", headers=staff).json()["items"][0]
    assert sub["status"] == "closed"


def test_paused_subscription_is_not_billed(client, staff, customer, catalog):
    cid, _ = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today())
    client.post(f"/api/subscriptions/{sub['id']}/actions/pause", headers=staff)
    assert run(client, staff, date.today())["invoices_created"] == 0


def test_product_discount_applies_automatically_and_tax_is_proportional(client, admin, staff, customer, catalog):
    cid, _ = customer
    client.post("/api/discounts", headers=admin, json={
        "code": "seats10", "discount_type": "percentage", "value": 10, "min_quantity": 10,
        "target_type": "product", "product_id": catalog["seat"]["id"]})
    start = date(2026, 2, 1)
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [
        {"product_id": catalog["product"]["id"], "quantity": 1},
        {"product_id": catalog["seat"]["id"], "quantity": 10}], start)
    run(client, staff, start)
    inv = client.get("/api/invoices/1", headers=staff).json()
    assert inv["discount_code"] == "SEATS10" and inv["discount_amount"] == 10.0
    seat = next(l for l in inv["lines"] if l["product_name"] == "Seat")
    assert seat["line_discount"] == 10.0 and seat["line_tax"] == 9.0  # tax on 90, not 100
    assert inv["total_amount"] == 200 - 10 + 19.0


def test_discount_below_threshold_not_applied(client, admin, staff, customer, catalog):
    cid, _ = customer
    client.post("/api/discounts", headers=admin, json={
        "code": "BIG", "discount_type": "fixed", "value": 50, "min_purchase": 1000})
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"]}], date(2026, 2, 1))
    run(client, staff, date(2026, 2, 1))
    assert client.get("/api/invoices/1", headers=staff).json()["discount_amount"] == 0


def test_discount_stops_when_used_up(client, admin, staff, customer, catalog):
    cid, _ = customer
    d = client.post("/api/discounts", headers=admin, json={"code": "ONCE", "discount_type": "fixed", "value": 25, "max_uses": 2}).json()
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 1))
    run(client, staff, date(2026, 4, 1))
    amounts = [i["discount_amount"] for i in sorted(invoices(client, staff), key=lambda i: i["period_start"])]
    assert amounts == [25, 25, 0, 0]
    assert next(x for x in client.get("/api/discounts", headers=admin).json() if x["id"] == d["id"])["current_uses"] == 2


def test_discount_stops_when_expired(client, admin, staff, customer, catalog):
    cid, _ = customer
    client.post("/api/discounts", headers=admin, json={
        "code": "JAN", "discount_type": "percentage", "value": 50, "start_date": "2026-01-01", "end_date": "2026-01-31"})
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 1))
    run(client, staff, date(2026, 2, 1))
    amounts = [i["discount_amount"] for i in sorted(invoices(client, staff), key=lambda i: i["period_start"])]
    assert amounts == [50, 0]


def test_subscription_specific_discount(client, admin, staff, customer, catalog):
    cid, _ = customer
    s1 = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 1))
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 1))
    client.post("/api/discounts", headers=admin, json={
        "code": "DEAL", "discount_type": "fixed", "value": 30, "subscription_id": s1["id"]})
    run(client, staff, date(2026, 1, 1))
    by_sub = {i["subscription_id"]: i for i in invoices(client, staff)}
    assert client.get(f"/api/invoices/{by_sub[s1['id']]['id']}", headers=staff).json()["discount_amount"] == 30
    assert len(by_sub) == 2 and sum(i["total_amount"] for i in by_sub.values()) == 110 - 33 + 110


def test_invoice_lifecycle_and_cancel_returns_discount_use(client, admin, staff, customer, catalog):
    cid, _ = customer
    client.post("/api/discounts", headers=admin, json={"code": "ONE", "discount_type": "fixed", "value": 5, "max_uses": 1})
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 1))
    run(client, staff, date(2026, 1, 1))
    assert client.post("/api/invoices/1/confirm", headers=staff).json()["status"] == "confirmed"
    assert client.post("/api/invoices/1/confirm", headers=staff).status_code == 400
    sent = client.post("/api/invoices/1/send", headers=staff).json()
    assert sent["sent_at"] is not None
    assert client.post("/api/invoices/1/cancel", headers=staff).json()["status"] == "cancelled"
    assert client.get("/api/discounts", headers=admin).json()[0]["current_uses"] == 0
    assert client.post("/api/invoices/1/cancel", headers=staff).status_code == 400


def test_print_invoice_html(client, staff, customer, catalog):
    cid, ch = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 1))
    run(client, staff, date(2026, 1, 1), auto_confirm=True)
    r = client.get("/api/invoices/1/print", headers=ch)
    assert r.status_code == 200 and "INV-00001" in r.text and "text/html" in r.headers["content-type"]


def test_customers_do_not_see_draft_invoices(client, staff, customer, catalog):
    cid, ch = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date(2026, 1, 1))
    run(client, staff, date(2026, 1, 1))
    assert client.get("/api/invoices", headers=ch).json()["total"] == 0
    assert client.get("/api/invoices/1", headers=ch).status_code == 404
    client.post("/api/invoices/1/confirm", headers=staff)
    assert client.get("/api/invoices", headers=ch).json()["total"] == 1


def test_tax_rule_per_product(client, admin, staff, customer, catalog):
    cid, _ = customer
    low = client.post("/api/taxes", headers=admin, json={"name": "Low", "rate_percentage": 5}).json()
    svc = client.post("/api/products", headers=admin, json={"name": "Service", "sales_price": 200, "tax_rule_id": low["id"]}).json()
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": svc["id"]}], date(2026, 1, 1))
    run(client, staff, date(2026, 1, 1))
    assert client.get("/api/invoices/1", headers=staff).json()["tax_amount"] == 10.0
    # only one default tax at a time
    client.post("/api/taxes", headers=admin, json={"name": "New default", "rate_percentage": 12, "is_default": True})
    assert sum(t["is_default"] for t in client.get("/api/taxes", headers=admin).json()) == 1
