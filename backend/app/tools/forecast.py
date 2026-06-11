"""forecast_foot_traffic — transparent, explainable match-day demand heuristic.

MVP model (honest by design — NO false precision):
  expected = baseline(hour) * match_multiplier(marquee, distance) * time_curve(hour vs kickoff)
             * weather_mod
Every output carries p10/p50/p90 (band scaled by confidence). Production swaps this for
TFT/DeepAR + hierarchical reconciliation (see PROJECT_PLAN.md §13), but the interface
is identical so the agent and UI don't change.
"""
from __future__ import annotations
import math
from functools import lru_cache
from datetime import datetime, timezone
from .. import mongo
from .weather import get_weather

# Rough per-business hourly baseline walk-ins on a normal day, by category.
_BASELINE = {
    "mexican_restaurant": 22, "italian_restaurant": 20, "american_restaurant": 18,
    "vietnamese_restaurant": 16, "sports_bar": 26, "bar": 24, "cafe": 28,
    "coffee_shop": 28, "convenience_store": 35, "grocery": 30, "parking": 40,
    "parking_lot": 40, "retail": 20, "default": 18,
}

# Evening hours (local) relative weighting around a kickoff.
def _time_curve(local_hour: int, kickoff_hour: int, category: str) -> float:
    """Pre-match peak ~2h before; post-match peak ~1-2h after for food/bars."""
    delta = local_hour - kickoff_hour
    if category in ("parking", "parking_lot"):
        # parking peaks 1-3h before kickoff
        return {(-3): 1.6, (-2): 2.2, (-1): 2.4, 0: 1.3, 1: 0.6}.get(delta, 0.4 if delta < -3 else 0.3)
    if category in ("sports_bar", "bar"):
        return {(-3): 1.4, (-2): 1.9, (-1): 2.1, 0: 2.3, 1: 2.0, 2: 1.8, 3: 1.2}.get(delta, 0.7)
    # restaurants/cafés: pre-match dinner + post-match late wave
    return {(-3): 1.2, (-2): 1.7, (-1): 1.9, 0: 1.4, 1: 1.6, 2: 1.9, 3: 1.5, 4: 1.0}.get(delta, 0.7)


def _distance_km(lat1, lon1, lat2, lon2) -> float:
    if None in (lat1, lon1, lat2, lon2):
        return 8.0
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _proximity_term(dist_km: float) -> float:
    # 0..1 surge intensity by distance: near venue catches the most; decays out.
    if dist_km <= 1:
        return 1.0
    if dist_km <= 3:
        return 0.8
    if dist_km <= 8:
        return 0.6   # close-in spillover
    if dist_km <= 15:
        return 0.45  # downtown SJ / Santana Row spillover band (~+40-70% peak)
    return 0.3


# Amplitude so a marquee match yields believable lift: ~+50-70% at spillover
# distance, ~+120-180% adjacent to the venue. Tuned to the research's worked figures.
SURGE_AMP = 1.6


@lru_cache(maxsize=1024)
def forecast_foot_traffic(business_id: str, match_id: str) -> dict:
    """Hourly foot-traffic surge for one business around one match, with p10/p50/p90. Memoized."""
    biz = mongo.get_business(business_id) or {}
    ev = mongo.get_event(match_id) or {}
    # Grounding + brittleness guard: if the business or match doesn't exist, do NOT fabricate a
    # surge from defaults (the agent could present invented foot-traffic), and do NOT make the
    # weather network call for a garbage date — return an honest, fast "unknown" instead.
    if not biz or not ev:
        missing = ", ".join(m for m, ok in (("business", biz), ("match", ev)) if not ok)
        return {"business_id": business_id, "match_id": match_id,
                "error": "unknown_business_or_match", "detail": f"not found: {missing}",
                "hours": [], "source": "guard"}
    category = biz.get("category", "default")
    base = _BASELINE.get(category, _BASELINE["default"])

    marquee = float(ev.get("marquee_score", 0.7))
    dist = _distance_km(biz.get("lat"), biz.get("lon"), ev.get("venue_lat"), ev.get("venue_lon"))
    prox = _proximity_term(dist)  # 0..1

    wx = get_weather(date=(ev.get("kickoff_local", "")[:10] or ""))
    wmod = float(wx.get("weather_mod", 1.0))

    # kickoff local hour
    try:
        kickoff_hour = int(ev.get("kickoff_local", "T18")[11:13])
    except Exception:
        kickoff_hour = 18

    hours = []
    total_p50 = 0.0
    incremental = 0.0  # extra walk-ins above a normal day (the surge itself)
    for h in range(max(0, kickoff_hour - 3), min(24, kickoff_hour + 5)):
        t = _time_curve(h, kickoff_hour, category) / 2.4   # normalize curve to ~0..1
        surge = marquee * prox * t * SURGE_AMP * wmod       # fractional lift this hour
        p50 = base * (1 + surge)
        lift_pct = round(surge * 100)
        # p10/p90 band widens as confidence drops
        conf = 0.5 + 0.25 * marquee  # 0.5..0.75-ish
        spread = (1 - conf) * 0.9
        hours.append({
            "hour_local": f"{h:02d}:00",
            "expected_walkins_p50": round(p50),
            "expected_walkins_p10": round(p50 * (1 - spread)),
            "expected_walkins_p90": round(p50 * (1 + spread)),
            "lift_vs_normal_pct": lift_pct,
        })
        total_p50 += p50
        incremental += base * surge

    return {
        "business_id": business_id, "match_id": match_id, "category": category,
        "distance_to_venue_km": round(dist, 1),
        "kickoff_local_hour": kickoff_hour,
        "weather": {"avg_temp_c": wx.get("avg_temp_c"), "max_precip_prob": wx.get("max_precip_prob"),
                    "inventory_hint": wx.get("inventory_hint")},
        "hours": hours,
        "window_total_walkins_p50": round(total_p50),
        "incremental_walkins_p50": round(incremental),
        "confidence": round(0.5 + 0.25 * marquee, 2),
        "drivers": [
            f"marquee_score={marquee}",
            f"{round(dist,1)}km_from_venue (proximity x{prox})",
            f"weather_mod={wmod}",
            "pre+post match time curve",
        ],
        "disclaimer": "Illustrative heuristic forecast. Calibrate with live GBP/POS data before relying on it.",
    }
