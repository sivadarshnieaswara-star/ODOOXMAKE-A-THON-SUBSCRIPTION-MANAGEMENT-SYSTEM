import time
from datetime import date, timedelta

from sqlalchemy import insert

from backend.app.models import Invoice, Payment, Plan, Subscription, SubscriptionLine, User

from .conftest import make_active_sub, register


def billed_invoice(client, staff, customer_id, plan_id, start, confirm=True):
    make_active_sub(client, staff, customer_id, plan_id, [], start)
    r = client.post("/api/billing/run", headers=staff, json={"as_of": start.isoformat(), "auto_confirm": confirm}).json()
    return client.get("/api/invoices", headers=staff, params={"q": r["invoice_numbers"][0]}).json()["items"][0]


def test_partial_then_full_payment_marks_paid(client, staff, customer, catalog):
    cid, _ = customer
    inv = billed_invoice(client, staff, cid, catalog["plan"]["id"], date.today())
    assert inv["total_amount"] == 110.0
    p1 = client.post("/api/payments", headers=staff, json={"invoice_id": inv["id"], "amount": 60, "payment_method": "upi", "note": "part"})
    assert p1.status_code == 201 and p1.json()["payment_number"] == "PAY-00001"
    mid = client.get(f"/api/invoices/{inv['id']}", headers=staff).json()
    assert mid["status"] == "confirmed" and mid["balance_due"] == 50.0
    client.post("/api/payments", headers=staff, json={"invoice_id": inv["id"], "amount": 50, "payment_method": "card"})
    done = client.get(f"/api/invoices/{inv['id']}", headers=staff).json()
    assert done["status"] == "paid" and done["balance_due"] == 0 and len(done["payments"]) == 2


def test_overpayment_and_draft_payment_rejected(client, staff, customer, catalog):
    cid, _ = customer
    inv = billed_invoice(client, staff, cid, catalog["plan"]["id"], date.today())
    r = client.post("/api/payments", headers=staff, json={"invoice_id": inv["id"], "amount": 500, "payment_method": "cash"})
    assert r.status_code == 400
    draft = billed_invoice(client, staff, cid, catalog["plan"]["id"], date.today(), confirm=False)
    r = client.post("/api/payments", headers=staff, json={"invoice_id": draft["id"], "amount": 10, "payment_method": "cash"})
    assert r.status_code == 400
    bad = client.post("/api/payments", headers=staff, json={"invoice_id": inv["id"], "amount": 10, "payment_method": "cheque"})
    assert bad.status_code == 422


def test_paid_invoice_cannot_be_cancelled(client, staff, customer, catalog):
    cid, _ = customer
    inv = billed_invoice(client, staff, cid, catalog["plan"]["id"], date.today())
    client.post("/api/payments", headers=staff, json={"invoice_id": inv["id"], "amount": 10, "payment_method": "cash"})
    assert client.post(f"/api/invoices/{inv['id']}/cancel", headers=staff).status_code == 400


def test_outstanding_and_overdue_lists(client, staff, customer, catalog):
    cid, _ = customer
    old = billed_invoice(client, staff, cid, catalog["plan"]["id"], date.today() - timedelta(days=45))  # due 15 days ago
    new = billed_invoice(client, staff, cid, catalog["plan"]["id"], date.today())
    outstanding = client.get("/api/invoices", headers=staff, params={"status": "outstanding"}).json()["items"]
    assert {i["id"] for i in outstanding} >= {old["id"], new["id"]}
    overdue = client.get("/api/analytics/overdue", headers=staff).json()
    assert overdue[0]["invoice_id"] == old["id"] and overdue[0]["days_overdue"] >= 15
    assert overdue[0]["email"] == "shop@example.com" and new["id"] not in {o["invoice_id"] for o in overdue}
    flagged = client.get("/api/invoices", headers=staff, params={"overdue": True}).json()["items"]
    assert all(i["is_overdue"] for i in flagged)


def test_customer_pays_own_invoice_in_portal(client, staff, customer, catalog):
    cid, ch = customer
    inv = billed_invoice(client, staff, cid, catalog["plan"]["id"], date.today())
    _, other = register(client, "nosy@example.com")
    assert client.post(f"/api/portal/invoices/{inv['id']}/pay", headers=other, json={}).status_code == 404
    r = client.post(f"/api/portal/invoices/{inv['id']}/pay", headers=ch, json={"payment_method": "card"})
    assert r.status_code == 201 and r.json()["amount"] == 110.0
    assert client.get(f"/api/invoices/{inv['id']}", headers=ch).json()["status"] == "paid"
    assert client.get("/api/payments", headers=ch).json()["total"] == 1
    assert client.get("/api/payments", headers=other).json()["total"] == 0


def test_analytics_summary_numbers(client, admin, staff, customer, catalog):
    cid, _ = customer
    yearly = client.post("/api/plans", headers=admin, json={"name": "Y", "cost": 1200, "billing_frequency": "yearly"}).json()
    make_active_sub(client, staff, cid, yearly["id"], [], date.today())  # MRR 100
    inv = billed_invoice(client, staff, cid, catalog["plan"]["id"], date.today() - timedelta(days=40))  # MRR 100, overdue
    client.post("/api/payments", headers=staff, json={"invoice_id": inv["id"], "amount": 10, "payment_method": "cash"})
    s = client.get("/api/analytics/summary", headers=staff).json()
    assert s["active_subscriptions"] == 2
    assert s["mrr"] == 200.0 and s["arr"] == 2400.0
    assert s["revenue_collected"] == 10.0
    assert s["outstanding_amount"] == 100.0 and s["overdue_count"] == 1
    filtered = client.get("/api/analytics/summary", headers=staff, params={"plan_id": yearly["id"]}).json()
    assert filtered["active_subscriptions"] == 1 and filtered["revenue_collected"] == 0
    assert client.get("/api/analytics/summary", headers=customer[1]).status_code == 403


def test_dashboard_sla_with_thousands_of_subscriptions(client, db_session, staff, customer, catalog):
    """5,000 subscriptions, 20,000 invoices, 15,000 payments: every finance query < 2 s."""
    cid, _ = customer
    today = date.today()
    with db_session() as s:
        customers = [{"email": f"c{i}@load.test", "password_hash": "x", "password_salt": "00", "role": "customer",
                      "name": f"Load {i}"} for i in range(500)]
        s.execute(insert(User), customers)
        first_cust = s.query(User).filter(User.email == "c0@load.test").one().id
        plan_ids = [catalog["plan"]["id"]]
        subs = [{"subscription_number": f"L-{i:06d}", "customer_id": first_cust + i % 500, "plan_id": plan_ids[0],
                 "start_date": today - timedelta(days=120), "status": "active" if i % 5 else "closed",
                 "payment_terms": "net_30", "next_billing_date": today + timedelta(days=i % 30)} for i in range(5000)]
        s.execute(insert(Subscription), subs)
        first_sub = s.query(Subscription).filter(Subscription.subscription_number == "L-000000").one().id
        s.execute(insert(SubscriptionLine), [{"subscription_id": first_sub + i, "product_id": catalog["seat"]["id"],
                                              "quantity": 1 + i % 7, "unit_price": 10.0, "tax_rate": 10.0} for i in range(5000)])
        invs = []
        for i in range(20000):
            issue = today - timedelta(days=i % 120)
            invs.append({"invoice_number": f"LI-{i:07d}", "subscription_id": first_sub + i % 5000,
                         "customer_id": first_cust + i % 500, "period_start": issue - timedelta(days=i // 5000 * 31),
                         "period_end": issue + timedelta(days=29), "issue_date": issue, "due_date": issue + timedelta(days=30),
                         "status": "paid" if i % 4 else "confirmed", "subtotal": 100.0, "tax_amount": 10.0,
                         "total_amount": 110.0, "balance_due": 0.0 if i % 4 else 110.0})
        s.execute(insert(Invoice), invs)
        first_inv = s.query(Invoice).filter(Invoice.invoice_number == "LI-0000000").one().id
        s.execute(insert(Payment), [{"payment_number": f"LP-{i:07d}", "invoice_id": first_inv + i,
                                     "customer_id": first_cust + i % 500, "amount": 110.0, "payment_method": "card",
                                     "payment_date": today - timedelta(days=i % 120)} for i in range(20000) if i % 4])
        s.commit()

    for path, params in [("/api/analytics/summary", {}), ("/api/analytics/summary", {"plan_id": catalog["plan"]["id"]}),
                         ("/api/analytics/overdue", {}), ("/api/subscriptions", {"status": "active"}),
                         ("/api/invoices", {"overdue": True}), ("/api/invoices", {"q": "LI-00199"}), ("/api/payments", {})]:
        t0 = time.perf_counter()
        r = client.get(path, headers=staff, params=params)
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, r.text
        assert elapsed < 2.0, f"{path} {params} took {elapsed:.2f}s"
    summary = client.get("/api/analytics/summary", headers=staff).json()
    assert summary["active_subscriptions"] == 4000
