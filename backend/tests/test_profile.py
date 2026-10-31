from datetime import date, timedelta

from .conftest import make_active_sub

FULL = {
    "job_title": "Head of Finance", "billing_email": "AP@Example.com", "website": "example.com", "industry": "Retail",
    "company_size": "11-50", "tax_id": "33abcde1234f1z5", "address_line1": "12 Main Road", "address_line2": "Guindy",
    "city": "Chennai", "state": "Tamil Nadu", "postal_code": "600032", "country": "India",
    "preferred_payment_method": "upi", "notify_offers": False,
}


def test_customer_updates_full_profile(client, customer):
    _, ch = customer
    me = client.patch("/api/auth/me", headers=ch, json=FULL).json()
    assert me["billing_email"] == "ap@example.com" and me["tax_id"] == "33ABCDE1234F1Z5"
    assert me["website"] == "https://example.com" and me["city"] == "Chennai" and me["notify_offers"] is False
    # only the fields sent change; null clears one
    me = client.patch("/api/auth/me", headers=ch, json={"address_line2": None}).json()
    assert me["address_line2"] is None and me["address_line1"] == "12 Main Road"
    # customers can't switch their own account off
    client.patch("/api/auth/me", headers=ch, json={"is_active": False})
    assert client.get("/api/auth/me", headers=ch).json()["is_active"] is True


def test_profile_validation(client, customer):
    _, ch = customer
    for bad in ({"tax_id": "33-ABC"}, {"tax_id": "AB12345678901Z5"}, {"billing_email": "not-an-email"},
                {"company_size": "huge"}, {"website": "nodot"}, {"preferred_payment_method": "cheque"}, {"name": ""}):
        assert client.patch("/api/auth/me", headers=ch, json=bad).status_code in (400, 422), bad


def test_billing_email_address_and_tax_id_are_used(client, admin, staff, customer, catalog):
    cid, ch = customer
    client.patch("/api/auth/me", headers=ch, json=FULL)
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today() - timedelta(days=45))
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    client.post("/api/invoices/1/send", headers=staff)
    sent = client.get("/api/emails", headers=admin).json()[0]
    assert sent["to_email"] == "ap@example.com"
    printed = client.get("/api/invoices/1/print", headers=ch).text
    assert "12 Main Road" in printed and "Chennai 600032, Tamil Nadu" in printed and "33ABCDE1234F1Z5" in printed
    client.post("/api/recommendations/collections-overdue/run", headers=staff)
    assert any(e["to_email"] == "ap@example.com" and "overdue" in e["subject"] for e in client.get("/api/emails", headers=admin).json())


def test_offer_emails_respect_opt_out(client, admin, staff, customer, catalog):
    cid, ch = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"], "quantity": 2}],
                    date.today() - timedelta(days=200))
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    for inv in client.get("/api/invoices?status=outstanding", headers=staff).json()["items"]:
        client.post("/api/payments", headers=staff, json={"invoice_id": inv["id"], "amount": inv["balance_due"], "payment_method": "card"})
    client.patch("/api/auth/me", headers=ch, json={"notify_offers": False})
    r = client.post("/api/recommendations/growth-annual/run", headers=staff).json()
    assert r["summary"].startswith("Sent 0")
    assert not any("annual billing" in e["subject"] for e in client.get("/api/emails", headers=admin).json())


def test_account_summary(client, staff, customer, catalog):
    cid, ch = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [], date.today() - timedelta(days=40))
    client.post("/api/billing/run", headers=staff, json={"auto_confirm": True})
    client.post("/api/payments", headers=staff, json={"invoice_id": 1, "amount": 110, "payment_method": "upi"})
    a = client.get("/api/portal/account", headers=ch).json()
    assert a["customer_id"] == f"CUST-{cid:05d}" and a["active"] == 1 and a["monthly_spend"] == 100.0
    assert a["lifetime_paid"] == 110.0 and a["last_payment"]["method"] == "upi" and 0 <= a["profile_complete"] <= 100
    assert client.get("/api/portal/account", headers=staff).status_code == 403


def test_staff_can_edit_customer_details(client, staff, customer):
    cid, ch = customer
    r = client.patch(f"/api/users/{cid}", headers=staff, json={"tax_id": "29AAGCR5678K1Z2", "city": "Bengaluru"})
    assert r.status_code == 200 and r.json()["tax_id"] == "29AAGCR5678K1Z2"
    assert client.get("/api/auth/me", headers=ch).json()["city"] == "Bengaluru"
