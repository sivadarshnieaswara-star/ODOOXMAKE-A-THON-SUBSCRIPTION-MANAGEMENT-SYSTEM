from datetime import date, timedelta

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect

from backend.app.database import add_missing_columns

from .conftest import make_active_sub


def act(client, headers, sid, action, **body):
    return client.post(f"/api/subscriptions/{sid}/actions/{action}", headers=headers, json=body or None)


def run(client, headers, as_of):
    return client.post("/api/billing/run", headers=headers, json={"as_of": as_of.isoformat()}).json()


# ---------- pause & resume ----------
def test_pause_with_resume_date_skips_paused_months(client, staff, customer, catalog):
    cid, _ = customer
    today = date.today()
    resume = today + timedelta(days=75)
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], today)
    run(client, staff, today)                                # first month billed
    paused = act(client, staff, sub["id"], "pause", resume_on=resume.isoformat(), reason="Seasonal closure").json()
    assert paused["status"] == "paused" and paused["resume_on"] == resume.isoformat()
    assert paused["pause_reason"] == "Seasonal closure"
    assert run(client, staff, today + timedelta(days=60))["invoices_created"] == 0   # still paused: nothing billed
    r = run(client, staff, resume)                           # resumes on its own and bills from the resume date
    assert r["subscriptions_resumed"] == 1 and r["invoices_created"] == 1
    starts = sorted(i["period_start"] for i in client.get("/api/invoices", headers=staff).json()["items"])
    assert starts == [today.isoformat(), resume.isoformat()]  # the paused months were never billed
    detail = client.get(f"/api/subscriptions/{sub['id']}", headers=staff).json()
    assert detail["status"] == "active" and detail["resume_on"] is None
    assert [e["action"] for e in detail["events"]][-2:] == ["pause", "auto_resume"]


def test_pause_rules(client, admin, staff, customer, catalog):
    cid, ch = customer
    plan = client.post("/api/plans", headers=admin, json={"name": "Capped", "cost": 10, "allow_pause": True,
                                                         "max_pause_days": 30}).json()
    sub = make_active_sub(client, staff, cid, plan["id"], [], date.today())
    past = act(client, staff, sub["id"], "pause", resume_on=(date.today() - timedelta(days=1)).isoformat())
    assert past.status_code == 400
    too_long = act(client, staff, sub["id"], "pause", resume_on=(date.today() + timedelta(days=45)).isoformat())
    assert too_long.status_code == 400 and "30 days" in too_long.json()["detail"]
    # no date on a capped plan: resumes automatically at the cap
    paused = act(client, ch, sub["id"], "pause").json()   # the customer can pause their own subscription
    assert paused["resume_on"] == (date.today() + timedelta(days=30)).isoformat()
    resumed = act(client, ch, sub["id"], "resume").json()
    assert resumed["status"] == "active" and resumed["paused_at"] is None


def test_open_ended_pause_needs_manual_resume(client, staff, customer, catalog):
    cid, _ = customer
    sub = make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today())
    act(client, staff, sub["id"], "pause")
    assert run(client, staff, date.today() + timedelta(days=200))["subscriptions_resumed"] == 0


def test_add_missing_columns_migrates_old_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Table("plans", MetaData(), Column("id", Integer, primary_key=True), Column("name", String)).create(engine)
    added = add_missing_columns(engine)
    assert "plans.max_pause_days" in added
    assert "max_pause_days" in {c["name"] for c in inspect(engine).get_columns("plans")}
    assert add_missing_columns(engine) == []


# ---------- recommendations ----------
def recs(client, headers):
    return {r["key"]: r for r in client.get("/api/recommendations", headers=headers).json()["items"]}


def test_recommendations_need_staff(client, customer):
    assert client.get("/api/recommendations", headers=customer[1]).status_code == 403


def test_overdue_invoices_produce_reminders(client, admin, staff, customer, catalog):
    cid, _ = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today() - timedelta(days=60))
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    r = recs(client, staff)
    assert r["collections-overdue"]["priority"] == "high" and r["collections-overdue"]["impact"] > 0
    out = client.post("/api/recommendations/collections-overdue/run", headers=staff).json()
    assert out["summary"].startswith("Sent ")
    emails = client.get("/api/emails", headers=admin).json()
    assert any("overdue" in e["subject"] for e in emails)
    # acted on: hidden for a while, logged in the activity feed
    data = client.get("/api/recommendations", headers=staff).json()
    assert next(x for x in data["items"] if x["key"] == "collections-overdue")["dismissed"] is True
    assert data["activity"][0]["summary"] == out["summary"]


def test_dismiss_and_restore(client, staff, customer, catalog):
    cid, _ = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today())   # due today
    assert recs(client, staff)["billing-due"]["dismissed"] is False
    client.post("/api/recommendations/billing-due/dismiss", headers=staff)
    assert recs(client, staff)["billing-due"]["dismissed"] is True
    client.post("/api/recommendations/billing-due/restore", headers=staff)
    assert recs(client, staff)["billing-due"]["dismissed"] is False


def test_autopilot_chains_billing_confirm_and_reminders(client, admin, staff, customer, catalog):
    cid, _ = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today() - timedelta(days=70), terms="net_15")
    assert client.post("/api/recommendations/autopilot", headers=staff).status_code == 403
    done = client.post("/api/recommendations/autopilot", headers=admin).json()["actions"]
    summaries = " | ".join(d["summary"] for d in done)
    assert "Billing run created" in summaries and "Confirmed" in summaries and "payment reminder" in summaries
    invs = client.get("/api/invoices", headers=admin).json()["items"]
    assert invs and all(i["status"] == "confirmed" for i in invs)


def test_annual_offer_for_loyal_monthly_customers(client, staff, customer, catalog):
    cid, _ = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"], "quantity": 2}],
                    date.today() - timedelta(days=200))
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    for inv in client.get("/api/invoices?status=outstanding", headers=staff).json()["items"]:
        client.post("/api/payments", headers=staff, json={"invoice_id": inv["id"], "amount": inv["balance_due"], "payment_method": "card"})
    r = recs(client, staff)
    assert r["growth-annual"]["impact"] == 240.0                # 2 seats x $10 x 12
    assert client.post("/api/recommendations/growth-annual/run", headers=staff).status_code == 200


def test_link_only_recommendation_cannot_run(client, staff):
    assert client.post("/api/recommendations/pricing-discounts/run", headers=staff).status_code == 400
