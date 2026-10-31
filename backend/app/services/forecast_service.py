"""Revenue forecasting by Monte Carlo simulation.

1. History: month-end MRR rebuilt from every subscription that was ever activated, plus the new
   and churned MRR in each month and how much of what was invoiced actually got collected.
2. Fit: monthly churn as a Beta distribution, new deals per month as a Poisson rate with a damped
   linear trend, deal sizes resampled from real deals, collection rate as a Beta distribution.
3. Simulate: thousands of 'possible futures', month by month:
       MRR[t+1] = MRR[t] * (1 - churn) + sum(new deals)
   then report percentile bands, the ARR distribution, the odds of hitting a target, and which
   lever (churn vs new business) moves the outcome most.
"""
import math
import random
import statistics
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import Invoice, Subscription, SubscriptionEvent
from .analytics_service import MONTHLY_FACTOR

PERCENTILES = (5, 25, 50, 75, 95)


# ---------- history ----------
def _month_end(d: date) -> date:
    return d.replace(day=1) + relativedelta(months=1) - timedelta(days=1)


def build_history(db: Session, months: int = 18, today: date | None = None) -> dict:
    today = today or date.today()
    activated = set(db.scalars(select(SubscriptionEvent.subscription_id)
                               .where(SubscriptionEvent.action.in_(("activate", "self_service")))))
    subs = db.scalars(select(Subscription).where(Subscription.id.in_(activated))
                      .options(selectinload(Subscription.lines), selectinload(Subscription.plan))).all()
    book = [(s.start_date, s.closed_at, s.recurring_amount * MONTHLY_FACTOR[s.plan.billing_frequency], s.status, s.customer_id)
            for s in subs]

    # Month ends for the past `months` months, then today as the last point.
    points = [_month_end(today - relativedelta(months=k)) for k in range(months, 0, -1)] + [today]

    def mrr_at(d: date) -> float:
        return sum(m for start, closed, m, status, _ in book
                   if start <= d and (closed is None or closed > d) and not (d == today and status == "paused"))

    rows, prev = [], None
    for d in points:
        lo = prev or date.min
        new = [m for start, _, m, _, _ in book if lo < start <= d]
        lost = [m for _, closed, m, _, _ in book if closed and lo < closed <= d]
        base = mrr_at(prev) if prev else 0.0
        rows.append({"date": d.isoformat(), "month": d.strftime("%Y-%m"), "mrr": round(mrr_at(d), 2),
                     "new_deals": len(new), "new_mrr": round(sum(new), 2), "churned_deals": len(lost),
                     "churned_mrr": round(sum(lost), 2), "churn_rate": (sum(lost) / base) if base > 0 else None})
        prev = d

    # Collection rate: of invoices issued 60+ days ago (inside the window), how much has been paid.
    window_start = points[0] - relativedelta(months=1)
    issued, outstanding = db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0), func.coalesce(func.sum(Invoice.balance_due), 0))
        .where(Invoice.status.in_(("confirmed", "paid")), Invoice.issue_date >= window_start,
               Invoice.issue_date <= today - timedelta(days=60))).one()
    collection_rate = (issued - outstanding) / issued if issued else None

    current = [(cid, m) for start, closed, m, status, cid in book if start <= today and closed is None and status == "active"]
    by_customer: dict[int, float] = {}
    for cid, m in current:
        by_customer[cid] = by_customer.get(cid, 0) + m
    current_mrr = sum(by_customer.values())
    top_share = max(by_customer.values()) / current_mrr if current_mrr else 0.0

    recent_cutoff = today - relativedelta(months=12)
    deal_sizes = [m for start, _, m, _, _ in book if start > recent_cutoff and m > 0] or [m for _, _, m, _, _ in book if m > 0]
    return {"rows": rows, "current_mrr": round(current_mrr, 2), "collection_rate": collection_rate,
            "deal_sizes": deal_sizes, "active_customers": len(by_customer), "top_customer_share": top_share,
            "subscriptions_seen": len(book)}


# ---------- fitting ----------
def _beta_params(mean: float, var: float) -> tuple[float, float]:
    """Method-of-moments Beta fit, kept well-behaved for small or noisy samples."""
    mean = min(max(mean, 0.002), 0.6)
    var = min(max(var, 1e-6), mean * (1 - mean) * 0.5)
    k = mean * (1 - mean) / var - 1
    return max(mean * k, 0.5), max((1 - mean) * k, 0.5)


def fit(history: dict) -> dict:
    rows = history["rows"][-13:]   # last 12 complete months + this month
    churn = [r["churn_rate"] for r in rows if r["churn_rate"] is not None]
    churn_mean = statistics.fmean(churn) if len(churn) >= 3 else 0.03
    churn_var = statistics.pvariance(churn) if len(churn) >= 3 else 0.0002
    a, b = _beta_params(churn_mean, churn_var)

    counts = [r["new_deals"] for r in rows[:-1]] or [0]   # this month is still in progress
    recent = counts[-6:]
    lam = statistics.fmean(recent) if recent else 0.0
    slope = 0.0
    if len(counts) >= 4:   # least-squares slope of deals per month
        xs = range(len(counts))
        mx, my = statistics.fmean(xs), statistics.fmean(counts)
        sxx = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, counts)) / sxx if sxx else 0.0

    coll = history["collection_rate"]
    coll_mean = min(max(coll if coll is not None else 0.93, 0.3), 0.999)
    return {
        "churn_mean": churn_mean, "churn_sd": math.sqrt(churn_var), "churn_alpha": a, "churn_beta": b,
        "deals_per_month": lam, "deals_trend": slope, "avg_deal_mrr": statistics.fmean(history["deal_sizes"]) if history["deal_sizes"] else 0.0,
        "median_deal_mrr": statistics.median(history["deal_sizes"]) if history["deal_sizes"] else 0.0,
        "collection_rate": coll_mean, "months_of_history": sum(1 for r in rows if r["mrr"] > 0),
    }


# ---------- simulation ----------
def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:   # normal approximation keeps big rates fast
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def simulate(params: dict, start_mrr: float, deal_sizes: list[float], *, months: int, sims: int, churn_mult: float = 1.0,
             growth_mult: float = 1.0, collection: float | None = None, seed: int = 42) -> tuple[list[list[float]], list[list[float]]]:
    """Return (mrr_paths, cash_paths), each sims x months."""
    rng = random.Random(seed)
    a, b = params["churn_alpha"], params["churn_beta"]
    lam0, slope = params["deals_per_month"], params["deals_trend"]
    coll_mean = collection if collection is not None else params["collection_rate"]
    ca, cb = _beta_params(coll_mean, 0.0004) if coll_mean < 0.999 else (999.0, 0.5)
    sizes = deal_sizes or [0.0]
    mrr_paths, cash_paths = [], []
    for _ in range(sims):
        m = start_mrr
        coll = rng.betavariate(ca, cb)
        path, cash = [], []
        for t in range(months):
            churn = min(0.95, rng.betavariate(a, b) * churn_mult)
            lam = max(0.0, (lam0 + slope * 0.5 * (t + 1)) * growth_mult)   # trend damped by half
            new = sum(rng.choice(sizes) for _ in range(_poisson(rng, lam)))
            m = m * (1 - churn) + new
            path.append(m)
            cash.append(m * coll)
        mrr_paths.append(path)
        cash_paths.append(cash)
    return mrr_paths, cash_paths


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _median_final(paths: list[list[float]]) -> float:
    return _pct(sorted(p[-1] for p in paths), 50)


def forecast(db: Session, *, months: int = 12, sims: int = 2000, churn_mult: float = 1.0, growth_mult: float = 1.0,
             collection: float | None = None, target_arr: float | None = None, seed: int = 42,
             today: date | None = None) -> dict:
    today = today or date.today()
    history = build_history(db, today=today)
    params = fit(history)
    start = history["current_mrr"]
    sizes = history["deal_sizes"]
    kw = dict(months=months, churn_mult=churn_mult, growth_mult=growth_mult, collection=collection)
    paths, cash = simulate(params, start, sizes, sims=sims, seed=seed, **kw)

    labels = [(today.replace(day=1) + relativedelta(months=t + 1)).strftime("%Y-%m") for t in range(months)]
    bands = []
    for t in range(months):
        col = sorted(p[t] for p in paths)
        bands.append({"month": labels[t], **{f"p{p}": round(_pct(col, p), 2) for p in PERCENTILES},
                      "mean": round(statistics.fmean(col), 2)})

    final_arr = sorted(p[-1] * 12 for p in paths)
    start_arr = start * 12
    target = target_arr if target_arr else round(max(start_arr * 1.25, 1000), -3)
    p_target = sum(1 for v in final_arr if v >= target) / sims
    p_decline = sum(1 for v in final_arr if v < start_arr) / sims
    cash_totals = sorted(sum(c) for c in cash)

    # ARR histogram for the final month.
    lo, hi = final_arr[0], final_arr[-1]
    bins = 24
    width = (hi - lo) / bins or 1
    counts = [0] * bins
    for v in final_arr:
        counts[min(bins - 1, int((v - lo) / width))] += 1
    histogram = [{"from": round(lo + i * width, 2), "to": round(lo + (i + 1) * width, 2), "count": c} for i, c in enumerate(counts)]

    # Driver analysis with common random numbers: same seed, one lever changed at a time.
    n = min(sims, 1000)
    base_med = _median_final(simulate(params, start, sizes, sims=n, seed=seed, **kw)[0])
    churn_med = _median_final(simulate(params, start, sizes, sims=n, seed=seed, **{**kw, "churn_mult": churn_mult * 0.75})[0])
    growth_med = _median_final(simulate(params, start, sizes, sims=n, seed=seed, **{**kw, "growth_mult": growth_mult * 1.25})[0])
    drivers = {"churn_minus_25pct_arr": round((churn_med - base_med) * 12, 2),
               "growth_plus_25pct_arr": round((growth_med - base_med) * 12, 2)}

    median_final = bands[-1]["p50"] if bands else start
    summary = {
        "start_mrr": round(start, 2), "start_arr": round(start_arr, 2),
        "median_mrr": round(median_final, 2), "median_arr": round(median_final * 12, 2),
        "p5_arr": round(_pct(final_arr, 5), 2), "p95_arr": round(_pct(final_arr, 95), 2),
        "growth_pct": round((median_final / start - 1) * 100, 1) if start else None,
        "target_arr": target, "p_target": round(p_target, 4), "p_decline": round(p_decline, 4),
        "expected_cash": round(statistics.fmean(cash_totals), 2), "cash_p5": round(_pct(cash_totals, 5), 2),
        "cash_p95": round(_pct(cash_totals, 95), 2),
    }
    return {
        "as_of": today.isoformat(), "months": months, "sims": sims, "seed": seed,
        "assumptions": {"churn_mult": churn_mult, "growth_mult": growth_mult, "collection": collection},
        "history": [{"month": r["month"], "mrr": r["mrr"], "new_mrr": r["new_mrr"], "churned_mrr": r["churned_mrr"],
                     "new_deals": r["new_deals"], "churned_deals": r["churned_deals"]} for r in history["rows"]],
        "bands": bands, "histogram": histogram, "summary": summary, "drivers": drivers,
        "model": {**{k: round(v, 5) if isinstance(v, float) else v for k, v in params.items()},
                  "active_customers": history["active_customers"], "subscriptions_seen": history["subscriptions_seen"],
                  "top_customer_share": round(history["top_customer_share"], 4), "deals_sampled": len(sizes)},
        "insights": insights(summary, drivers, params, history, months, churn_mult, growth_mult),
    }


# ---------- narrative ----------
def _money(v: float) -> str:
    return f"${v:,.0f}"


def insights(s: dict, drivers: dict, params: dict, history: dict, months: int, churn_mult: float, growth_mult: float) -> list[dict]:
    out = []
    if params["months_of_history"] < 6:
        out.append({"tone": "amber", "title": "Thin history",
                    "body": f"Only {params['months_of_history']} months of revenue history were found, so the bands are wide. "
                            "Load the simulation data or let more months accumulate for a sharper forecast."})
    if s["growth_pct"] is not None:
        direction = "grow" if s["growth_pct"] >= 0 else "shrink"
        out.append({"tone": "green" if s["growth_pct"] >= 0 else "red", "title": "Most likely outcome",
                    "body": f"In {months} months MRR is most likely to {direction} from {_money(s['start_mrr'])} to "
                            f"{_money(s['median_mrr'])} ({s['growth_pct']:+.1f}%), an ARR of {_money(s['median_arr'])}. "
                            f"9 in 10 simulated futures land between {_money(s['p5_arr'])} and {_money(s['p95_arr'])} ARR."})
    out.append({"tone": "blue", "title": "Target",
                "body": f"{s['p_target'] * 100:.0f}% of simulations reach the {_money(s['target_arr'])} ARR target; "
                        f"{s['p_decline'] * 100:.0f}% end below today's ARR."})
    churn_gain, growth_gain = drivers["churn_minus_25pct_arr"], drivers["growth_plus_25pct_arr"]
    lever = "Cutting churn" if churn_gain >= growth_gain else "Winning more new business"
    out.append({"tone": "brand", "title": "Biggest lever",
                "body": f"{lever} moves the forecast most. Reducing churn by a quarter adds about {_money(churn_gain)} to median ARR, "
                        f"while 25% more new deals adds about {_money(growth_gain)}."})
    out.append({"tone": "slate", "title": "Churn",
                "body": f"Monthly revenue churn has averaged {params['churn_mean'] * 100:.1f}% "
                        f"(±{params['churn_sd'] * 100:.1f} pts){' before your adjustment' if churn_mult != 1 else ''}, "
                        f"about {_money(s['start_mrr'] * params['churn_mean'])} of MRR lost each month at today's size."})
    trend = params["deals_trend"]
    out.append({"tone": "slate", "title": "New business",
                "body": f"About {params['deals_per_month']:.1f} new subscriptions a month recently "
                        f"({'rising' if trend > 0.05 else 'falling' if trend < -0.05 else 'steady'}), with a typical deal "
                        f"of {_money(params['median_deal_mrr'])} MRR."})
    out.append({"tone": "amber" if params["collection_rate"] < 0.9 else "green", "title": "Cash",
                "body": f"{params['collection_rate'] * 100:.0f}% of invoiced revenue gets collected, so expect about "
                        f"{_money(s['expected_cash'])} in cash over the next {months} months "
                        f"(90% range {_money(s['cash_p5'])}–{_money(s['cash_p95'])})."})
    if history["top_customer_share"] > 0.25:
        out.append({"tone": "red", "title": "Concentration risk",
                    "body": f"Your largest customer is {history['top_customer_share'] * 100:.0f}% of MRR. Losing them would erase "
                            "a big slice of the forecast; the simulation does not model that one-off risk separately."})
    return out
