"""Profitability Forecast — turn the demand forecast into a business decision.

Net opportunity = incremental revenue - extra labor - extra inventory - ad spend
                  - spoilage risk - review-risk penalty.

Incremental revenue is built as a conversion chain so it's explainable:
  extra impressions x CTR x (direction/call/menu) conv x visit/order conv x AOV x capacity.
Visibility Score feeds CTR/conversion (a more-visible, more-complete profile converts
better). Everything is a low/high range — no false precision.
"""
from __future__ import annotations
from .. import mongo
from .forecast import forecast_foot_traffic
from .visibility import compute_visibility_score

# average order value (USD) by category — illustrative.
AOV = {
    "mexican_restaurant": 24, "taqueria": 18, "italian_restaurant": 38,
    "american_restaurant": 28, "vietnamese_restaurant": 20, "sports_bar": 30,
    "bar": 26, "cafe": 9, "coffee_shop": 9, "convenience_store": 12,
    "grocery": 18, "parking": 25, "parking_lot": 25, "fast_food_restaurant": 14,
}
# rough hourly fully-loaded labor cost per extra staff member.
LABOR_PER_STAFF_HR = 28
# inventory cost as a share of incremental revenue (COGS-ish).
INVENTORY_COGS = 0.30


def forecast_profitability(business_id: str, match_id: str, ad_budget: float = 120.0) -> dict:
    biz = mongo.get_business(business_id) or {}
    cat = biz.get("category", "default")
    fc = forecast_foot_traffic(business_id, match_id)
    vis = compute_visibility_score(business_id, match_id)
    vscore = vis["visibility_score"] / 100.0  # 0..1

    # the surge itself: extra covers above a normal day (from the forecast).
    incremental_covers = fc.get("incremental_walkins_p50", 0)

    # how much of the surge you actually CAPTURE depends on visibility/readiness.
    capture = 0.6 + 0.35 * vscore                 # 0.6 (weak profile) .. ~0.95 (strong)
    aov = AOV.get(cat, 20)
    capacity_conf = fc.get("confidence", 0.6)
    served = incremental_covers * capture
    rev_mid = served * aov
    rev_low, rev_high = round(rev_mid * 0.8), round(rev_mid * 1.25)

    # explainability: the search->visit conversion chain visibility improves.
    impressions = round(incremental_covers * (3 + 4 * vscore))
    ctr = 0.05 + 0.10 * vscore                    # 5%..15%
    intent_conv = 0.35 + 0.25 * vscore            # direction/call/menu click
    visit_conv = 0.45 + 0.20 * vscore             # of those, who visit/order

    # costs (proportional to the captured surge)
    extra_staff_hours = sum(max(0, s["staff"] - 3) for s in _staff_estimate(fc, cat))
    labor_cost = round(extra_staff_hours * LABOR_PER_STAFF_HR)
    inventory_cost = round(rev_mid * INVENTORY_COGS)
    spoilage_risk = round(inventory_cost * 0.10)
    # review risk: penalize if demand is high but the profile/hours can't fulfill it.
    review_risk_penalty = round(rev_mid * 0.08) if vscore < 0.6 else round(rev_mid * 0.03)

    total_cost = labor_cost + inventory_cost + round(ad_budget) + spoilage_risk
    net_low = rev_low - total_cost - review_risk_penalty
    net_high = rev_high - total_cost

    return {
        "business_id": business_id, "match_id": match_id, "category": cat,
        "visibility_score": vis["visibility_score"],
        "conversion_chain": {
            "incremental_covers": round(incremental_covers), "capture_rate": round(capture, 2),
            "impressions": impressions, "ctr": round(ctr, 3),
            "intent_conv": round(intent_conv, 3), "visit_conv": round(visit_conv, 3),
            "aov_usd": aov, "capacity_confidence": capacity_conf,
        },
        "incremental_revenue_usd": {"low": rev_low, "high": rev_high},
        "costs_usd": {
            "labor": labor_cost, "inventory": inventory_cost, "ad_spend": round(ad_budget),
            "spoilage_risk": spoilage_risk, "review_risk_penalty": review_risk_penalty,
        },
        "net_opportunity_usd": {"low": net_low, "high": net_high},
        "decision": (
            "Strong go — prepare now" if (net_low + net_high) / 2 > 300 else
            "Go, but fix the visibility/capacity gaps first" if (net_low + net_high) / 2 > 0 else
            "Marginal — only worth it after you close the visibility + capacity gaps"),
        "note": "Illustrative ranges. Calibrate AOV, conversion, and capacity with live GA4/GBP/POS data.",
    }


def _staff_estimate(fc: dict, category: str):
    base = 3 if category in ("cafe", "convenience_store", "coffee_shop") else 4
    out = []
    for h in fc.get("hours", []):
        lift = h.get("lift_vs_normal_pct", 0)
        out.append({"hour": h["hour_local"], "staff": max(base, round(base * (1 + lift / 100.0)))})
    return out
