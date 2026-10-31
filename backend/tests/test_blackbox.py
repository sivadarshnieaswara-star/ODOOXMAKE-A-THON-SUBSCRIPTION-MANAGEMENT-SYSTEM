from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from sqlalchemy import delete, select

from backend.app.models import BlackBoxEntry, Subscription
from backend.app.services import blackbox

from .conftest import make_active_sub, register


def box(client, headers, sid):
    r = client.get(f"/api/subscriptions/{sid}/blackbox", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_records_full_billing_story_in_order(client, staff, customer, catalog):
    cid, _ = customer
    start = date.today() - timedelta(days=40)
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"], "quantity": 5}], start)
    client.post("/api/billing/run", headers=staff, json={"as_of": start.isoformat()})
    client.post("/api/invoices/1/confirm", headers=staff)
    client.post("/api/invoices/1/send", headers=staff)
    client.post("/api/payments", headers=staff, json={"invoice_id": 1, "amount": 20, "payment_method": "upi"})
    client.post("/api/payments", headers=staff, json={"invoice_id": 1, "amount": 35, "payment_method": "card"})

    b = box(client, staff, sub["id"])
    kinds = [e["event_type"] for e in b["entries"]]
    assert kinds == ["created", "quotation_sent", "confirmed", "activated", "invoice_issued", "invoice_confirmed",
                     "invoice_sent", "payment_received", "payment_received", "invoice_paid"]
    assert [e["seq"] for e in b["entries"]] == list(range(1, 11))
    issued = b["entries"][4]
    assert issued["amount"] == 55.0 and issued["data"]["tax"] == 5.0 and issued["occurred_on"] == start.isoformat()
    assert "days late" in b["entries"][7]["summary"]                          # paid after the net-30 due date
    assert b["verification"] == {"ok": True, "entries": 10, "broken_at": None, "reason": None, "head": b["entries"][-1]["hash"]}
    # every entry points at the one before it
    for prev, cur in zip(b["entries"], b["entries"][1:]):
        assert cur["prev_hash"] == prev["hash"]


def test_pause_and_renew_details_are_recorded(client, admin, staff, customer, catalog):
    cid, _ = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today(), date.today() + timedelta(days=364))
    resume = (date.today() + timedelta(days=20)).isoformat()
    client.post(f"/api/subscriptions/{sub['id']}/actions/pause", headers=staff, json={"resume_on": resume, "reason": "Budget freeze"})
    client.post(f"/api/subscriptions/{sub['id']}/actions/resume", headers=staff)
    client.post(f"/api/subscriptions/{sub['id']}/actions/renew", headers=staff)
    entries = {e["event_type"]: e for e in box(client, staff, sub["id"])["entries"]}
    assert entries["paused"]["data"]["resume_on"] == resume and "Budget freeze" in entries["paused"]["summary"]
    # a 12-month term renews for another 12 calendar months
    assert entries["renewed"]["data"]["new_expiry"] == (date.today() + timedelta(days=364) + relativedelta(years=1)).isoformat()


def test_tampering_breaks_the_chain(client, db_session, staff, customer, catalog):
    cid, _ = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today())
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    assert box(client, staff, sub["id"])["verification"]["ok"]

    with db_session() as s:   # someone quietly edits the invoice amount in the record
        e = s.scalar(select(BlackBoxEntry).where(BlackBoxEntry.event_type == "invoice_issued"))
        e.amount = 1.0
        s.commit()
        seq = e.seq
    v = box(client, staff, sub["id"])["verification"]
    assert v["ok"] is False and v["broken_at"] == seq and "changed" in v["reason"]
    assert client.get("/api/blackbox/verify", headers=staff).json()["broken"][0]["subscription_id"] == sub["id"]

    with db_session() as s:   # deleting an entry is caught too
        s.execute(delete(BlackBoxEntry).where(BlackBoxEntry.seq == 2))
        s.commit()
    assert box(client, staff, sub["id"])["verification"]["broken_at"] == 3


def test_customer_copy_hides_internal_entries(client, admin, staff, customer, catalog):
    cid, ch = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today() - timedelta(days=60))
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    client.post("/api/recommendations/collections-overdue/run", headers=staff)        # internal reminder entries
    staff_view = box(client, staff, sub["id"])
    cust_view = box(client, ch, sub["id"])
    assert any(e["event_type"] == "reminder_sent" for e in staff_view["entries"])
    assert not any(e["internal"] for e in cust_view["entries"]) and cust_view["customer_copy"] is True
    assert cust_view["verification"]["ok"] and cust_view["verification"]["entries"] == len(staff_view["entries"])
    _, other = register(client, "nosy@example.com")
    assert client.get(f"/api/subscriptions/{sub['id']}/blackbox", headers=other).status_code == 404
    assert client.get(f"/api/subscriptions/{sub['id']}/blackbox/report", headers=other).status_code == 404


def test_report_document(client, staff, customer, catalog):
    cid, ch = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today() - timedelta(days=45))
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    html = client.get(f"/api/subscriptions/{sub['id']}/blackbox/report", headers=staff)
    assert html.status_code == 200 and "text/html" in html.headers["content-type"]
    body = html.text
    assert sub["subscription_number"] in body and "Chain verified" in body and "Flight summary" in body
    assert "overdue" in body                                                          # shows up under incidents
    assert "Customer copy" in client.get(f"/api/subscriptions/{sub['id']}/blackbox/report", headers=ch).text


def test_backfill_reconstructs_missing_records(client, db_session, staff, customer, catalog):
    cid, _ = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today() - timedelta(days=10))
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    with db_session() as s:   # pretend this subscription predates the recorder
        s.execute(delete(BlackBoxEntry))
        s.commit()
        assert blackbox.backfill_missing(s) == 1
        assert blackbox.backfill_missing(s) == 0                                       # idempotent
        sub_row = s.get(Subscription, sub["id"])
        chain = blackbox.entries(s, sub_row.id)
        assert blackbox.verify(s, sub_row)["ok"]
        assert {e.event_type for e in chain} >= {"created", "activated", "invoice_issued"}
        assert all('"reconstructed": true' in e.data_json for e in chain)
