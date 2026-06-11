"""Capacity / busy proxy — LEGAL.

We do NOT scrape Google Popular Times (that's what busy-hours-master does; rejected for
Maps-ToS risk). Instead we estimate crowd pressure from signals we're allowed to use: our
own match-window demand forecast, venue proximity/route flow, category, opt-in GA4/GBP/POS
(when connected), and user feedback ("line too long" / "too crowded").

Output borrows only the SHAPE of busy-hours (hourly percentage + now percentage); the
numbers are our estimate and are labeled as such — never presented as Google's data.
"""
from __future__ import annotations
from .forecast import forecast_foot_traffic
from .learning_loop import mongo as _fb_mongo  # feedback counts via mongo helper
from .owner_connectors import ga4_signals, pos_signals

CROWDY_CATS = {"sports_bar", "bar"}
SMALL_CATS = {"taqueria", "cafe", "coffee_shop", "sandwich_shop", "convenience_store"}


def _risk_from(pct: int) -> str:
    return "high" if pct >= 75 else "medium" if pct >= 45 else "low"


def estimate_capacity(place: dict, event: dict, requested_time: dict | None = None) -> dict:
    fc = forecast_foot_traffic(place.get("_id", ""), event.get("_id", "")) if event else {}
    hours = fc.get("hours", [])
    dist = fc.get("distance_to_venue_km", 8)
    cat = place.get("category", "")

    # synthesize an hourly "busy %" proxy from the forecast lift (busy-hours shape)
    week_hours = []
    peak_pct = 0
    for h in hours:
        lift = h.get("lift_vs_normal_pct", 0)
        pct = max(5, min(100, round(40 + lift * 0.5)))   # baseline 40% + surge
        if dist <= 8:
            pct = min(100, pct + 8)                       # spillover proximity bump
        week_hours.append({"hour": h["hour_local"], "percentage": pct})
        peak_pct = max(peak_pct, pct)

    # now %: at the asked hour if given, else the peak
    now_pct = peak_pct
    if requested_time and requested_time.get("has_time"):
        hh = f"{requested_time['hour']:02d}:00"
        now_pct = next((x["percentage"] for x in week_hours if x["hour"] == hh), peak_pct)

    # user-feedback override (opt-in real signal beats the proxy)
    fb = _fb_mongo.get_feedback_counts().get("by_business", {}).get(place.get("_id"), 0)

    crowd_risk = _risk_from(peak_pct) if hours else "unknown"
    wait_risk = crowd_risk
    if cat in CROWDY_CATS and crowd_risk != "unknown":
        crowd_risk = "high" if crowd_risk in ("medium", "high") else crowd_risk
    family_chaos_risk = ("high" if (cat in CROWDY_CATS and peak_pct >= 45)
                         else "medium" if peak_pct >= 60 else "low") if hours else "unknown"
    signals = ["match_window_forecast", "venue_proximity", "category"] + (["user_feedback"] if fb else [])
    confidence = 0.4 if hours else 0.2   # proxy, not measured

    # owner-authorized live signals beat the proxy (real measurement)
    bid = place.get("_id", "")
    g = ga4_signals(bid)
    if g.get("available"):
        signals.append("ga4_realtime"); confidence = 0.75
        if (g.get("realtime_users") or 0) >= 50 or g.get("spike"):
            crowd_risk = wait_risk = "high"
    p = pos_signals(bid)
    if p.get("available"):
        signals.append("pos"); confidence = max(confidence, 0.8)
        if p.get("sold_out") or (p.get("wait_minutes") or 0) >= 30:
            crowd_risk = wait_risk = "high"

    backup_needed = crowd_risk == "high" or wait_risk == "high"

    return {
        "crowd_risk": crowd_risk, "wait_risk": wait_risk,
        "family_chaos_risk": family_chaos_risk, "backup_needed": backup_needed,
        "now_percentage": now_pct, "peak_percentage": peak_pct,
        "week": [{"day": "matchday", "hours": week_hours}],
        "confidence": confidence,
        "signals_used": signals,
        "source": "estimated_proxy",
        "disclaimer": "Estimated crowd pressure from our match-window forecast — NOT Google "
                      "Popular Times (we don't scrape it).",
    }
