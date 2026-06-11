"""Search-to-Revenue funnel — models how a fan's search becomes revenue, and finds
where conversion leaks for THIS business.

  search interest -> impression -> profile view -> menu/photo/review interaction
  -> call/direction/order/reservation -> visit -> purchase -> review -> future visibility

Uses first-party GA4/GBP deltas when available, else estimates from the forecast +
visibility score. The valuable output is the LEAK: the stage with abnormal drop-off
tied to a fixable readiness gap.
"""
from __future__ import annotations
from .. import mongo
from .signals import get_visitor_signals
from .visibility import compute_visibility_score
from .classify import classify_business
from .forecast import forecast_foot_traffic


def _mw(sig, key):
    return (sig.get("deltas", {}).get(key, {}) or {}).get("match_window")


def search_to_revenue_funnel(business_id: str, match_id: str) -> dict:
    biz = mongo.get_business(business_id) or {}
    sig = get_visitor_signals(business_id, match_id)
    vis = compute_visibility_score(business_id, match_id)
    cls = classify_business(biz)
    fc = forecast_foot_traffic(business_id, match_id)
    vscore = vis["visibility_score"] / 100.0
    have = sig.get("available")

    if have:
        sessions = _mw(sig, "sessions") or 0
        menu = _mw(sig, "menu_clicks") or 0
        directions = _mw(sig, "direction_clicks") or 0
        calls = _mw(sig, "call_clicks") or 0
        reservations = _mw(sig, "reservation_clicks") or 0
        impressions = round(sessions / max(0.06 + 0.10 * vscore, 0.06))  # back out from CTR
    else:
        incr = fc.get("incremental_walkins_p50", 0)
        impressions = round(incr * (3 + 4 * vscore))
        sessions = round(impressions * (0.06 + 0.10 * vscore))
        menu = round(sessions * (0.35 + 0.25 * vscore))
        directions = round(menu * 0.5)
        calls = round(menu * 0.15)
        reservations = round(menu * 0.10 * (1 if biz.get("gbp", {}).get("has_reservation_link") else 0.2))

    actions = directions + calls + reservations
    visits = round(actions * (0.55 + 0.2 * vscore))
    purchases = round(visits * 0.85)
    reviews = round(purchases * 0.04)

    stages = [
        {"stage": "search interest", "count": None, "note": "rising match-window queries"},
        {"stage": "impression / Maps listing", "count": impressions},
        {"stage": "profile view (session)", "count": sessions},
        {"stage": "menu / photo / review check", "count": menu},
        {"stage": "call / directions / order / reservation", "count": actions},
        {"stage": "visit", "count": visits},
        {"stage": "purchase", "count": purchases},
        {"stage": "review (→ future visibility)", "count": reviews},
    ]

    # leak detection: worst drop tied to a fixable gap
    leaks = []
    gbp = biz.get("gbp", {})
    if sessions and menu / max(sessions, 1) < 0.3 and not gbp.get("has_menu_link"):
        leaks.append({"stage": "menu / photo / review check",
                      "issue": "few profile viewers open the menu", "fix": "Add a menu link + 10+ photos"})
    if menu and reservations / max(menu, 1) < 0.05 and not gbp.get("has_reservation_link"):
        leaks.append({"stage": "call / directions / order / reservation",
                      "issue": "interested visitors can't book/order", "fix": "Add an order/reservation link"})
    if not cls["late_night_capable"]:
        leaks.append({"stage": "visit", "issue": "closes before the post-match wave",
                      "fix": "Set match-day special hours into the late window"})
    if cls["language_readiness"] == "english_only":
        leaks.append({"stage": "profile view (session)", "issue": "rising non-English demand not served",
                      "fix": "Add bilingual profile/menu copy"})

    return {
        "business_id": business_id, "match_id": match_id,
        "signals_source": "first-party GA4/GBP" if have else "estimated from forecast + visibility",
        "stages": stages,
        "primary_leak": leaks[0] if leaks else None,
        "all_leaks": leaks,
        "summary": (f"Tourists are searching for places like {biz.get('name')}, but conversion leaks at "
                    f"'{leaks[0]['stage']}': {leaks[0]['issue']}. Fix: {leaks[0]['fix']}.") if leaks
                   else "Conversion path is healthy across the funnel.",
    }
