from datetime import date

from backend.app.services.forecast_service import _beta_params, _pct, fit, simulate

from .conftest import make_active_sub


def load_sim(client, admin, months=8, customers=40):
    r = client.post("/api/forecast/simulation-data", headers=admin, json={"months": months, "customers": customers})
    assert r.status_code == 200, r.text
    return r.json()


def test_simulation_data_is_admin_only_and_loads_once(client, admin, staff):
    assert client.post("/api/forecast/simulation-data", headers=staff, json={}).status_code == 403
    stats = load_sim(client, admin)
    assert stats["customers"] == 40 and stats["subscriptions"] == 40 and stats["payments"] > 0
    assert client.post("/api/forecast/simulation-data", headers=admin, json={}).status_code == 400
    # the simulated book flows through the normal billing engine
    assert client.get("/api/invoices", headers=admin).json()["total"] > 40


def test_forecast_requires_staff(client, customer):
    assert client.get("/api/forecast", headers=customer[1]).status_code == 403


def test_forecast_shape_and_ordering(client, admin):
    load_sim(client, admin)
    r = client.get("/api/forecast", headers=admin, params={"months": 6, "sims": 500}).json()
    assert len(r["bands"]) == 6 and r["simulation_data_loaded"] is True
    for b in r["bands"]:
        assert b["p5"] <= b["p25"] <= b["p50"] <= b["p75"] <= b["p95"]
    assert sum(h["count"] for h in r["histogram"]) == 500
    assert 0 <= r["summary"]["p_target"] <= 1 and r["summary"]["start_mrr"] > 0
    assert r["history"][-1]["mrr"] == r["summary"]["start_mrr"]
    assert {i["title"] for i in r["insights"]} >= {"Most likely outcome", "Target", "Biggest lever"}


def test_forecast_is_reproducible_and_responds_to_levers(client, admin):
    load_sim(client, admin)
    base = dict(months=12, sims=600, seed=1)
    a = client.get("/api/forecast", headers=admin, params=base).json()["summary"]
    b = client.get("/api/forecast", headers=admin, params=base).json()["summary"]
    assert a == b
    worse = client.get("/api/forecast", headers=admin, params={**base, "churn": 2.0}).json()["summary"]
    better = client.get("/api/forecast", headers=admin, params={**base, "growth": 2.0}).json()["summary"]
    assert worse["median_arr"] < a["median_arr"] < better["median_arr"]
    low_cash = client.get("/api/forecast", headers=admin, params={**base, "collection": 0.5}).json()["summary"]
    assert low_cash["expected_cash"] < a["expected_cash"]


def test_history_rebuilds_mrr_from_subscriptions(client, admin, staff, customer, catalog):
    cid, _ = customer
    make_active_sub(client, staff, cid, catalog["plan"]["id"], [{"product_id": catalog["seat"]["id"], "quantity": 3}],
                    date(2026, 1, 10))
    hist = client.get("/api/forecast", headers=admin, params={"months": 3, "sims": 200}).json()["history"]
    jan = next(h for h in hist if h["month"] == "2026-01")
    assert jan["mrr"] == 30.0 and jan["new_deals"] == 1


def test_simulation_math():
    params = {"churn_alpha": 2, "churn_beta": 98, "deals_per_month": 0, "deals_trend": 0, "collection_rate": 1.0}
    paths, cash = simulate(params, 1000, [], months=12, sims=300, seed=3)
    finals = sorted(p[-1] for p in paths)
    # ~2%/month churn with no new business: about 1000 * 0.98^12 ≈ 785 left
    assert 700 < _pct(finals, 50) < 860
    assert all(c[-1] <= p[-1] + 1e-6 for p, c in zip(paths, cash))
    a, b = _beta_params(0.03, 0.0001)
    assert abs(a / (a + b) - 0.03) < 1e-3


def test_fit_handles_empty_history():
    params = fit({"rows": [], "collection_rate": None, "deal_sizes": []})
    assert params["churn_mean"] == 0.03 and params["deals_per_month"] == 0 and params["collection_rate"] == 0.93
