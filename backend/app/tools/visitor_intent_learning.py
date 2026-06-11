"""Visitor-Intent Learning Layer.

We do NOT hard-code "nationality X wants food Y". We treat visitor intent as a set of
TESTABLE HYPOTHESES and let observable, privacy-safe signals raise or lower our
confidence in each one. Each hypothesis declares:
  - what the visitor may be seeking
  - why World Cup tourism could create that intent
  - which signals (GA4 / GBP / Places / Ads / Trends / transit / event context) confirm it
  - which local-business actions respond to it
  - which conversion metrics show whether the action worked

Confidence is EARNED from evidence:
  - ambient signals (Trends, aggregate source-market mix, event context) can reach MEDIUM
  - first-party confirmation (GA4/GBP deltas) is required for HIGH
  - with no signals, an intent stays a LOW-confidence hypothesis to MONITOR

All signals are aggregate. No ethnicity, no individual identification.
"""
from __future__ import annotations
from .. import mongo
from .signals import get_visitor_signals

# Hypotheses — the "what to look for", not "what we assume is true".
HYPOTHESES = [
    {
        "id": "convenience_seeker",
        "label": "Convenience seeker",
        "seeks": "Fast food/coffee/water, short walk, open now, quick service near the venue.",
        "why_world_cup": "Visitors are time-pressured and don't know the area before kickoff.",
        "signals": ["sessions surge", "direction-click surge", "'food near' / 'near me' Trends"],
        "actions": ["extend hours through the window", "enable pickup/order-ahead", "show distance + 'open now' on landing page"],
        "metrics": ["direction_clicks", "call_clicks", "order_clicks"],
        "needs": ["mexican_restaurant", "taqueria", "cafe", "fast_food_restaurant", "convenience_store"],
    },
    {
        "id": "trust_under_uncertainty",
        "label": "Trust-under-uncertainty seeker",
        "seeks": "Proof it's good & legit — ratings, recent reviews, photos, clear menu.",
        "why_world_cup": "No local knowledge, so visitors lean hard on prominence signals.",
        "signals": ["menu-view surge", "high rating/review base", "review-response gaps"],
        "actions": ["add 10+ recent photos", "respond to recent reviews", "add a clear menu link"],
        "metrics": ["menu_clicks", "profile_views", "save_clicks"],
        "needs": [],
    },
    {
        "id": "language_comfort_seeker",
        "label": "Language-comfort seeker",
        "seeks": "Menus/signage/service in a familiar language under travel stress.",
        "why_world_cup": "Match draws an aggregate non-English-language visitor segment.",
        "signals": ["non-English GA4 session ratio rising", "non-English keyword Trends", "GBP interactions after a localized post"],
        "actions": ["localized GBP post", "bilingual landing page", "bilingual menu QR", "staff phrase card"],
        "metrics": ["menu_clicks", "direction_clicks", "reservation_clicks"],
        "needs": [],
    },
    {
        "id": "familiar_food_seeker",
        "label": "Familiar-food seeker",
        "seeks": "Food that matches their comfort zone / match-day identity — a taste of home.",
        "why_world_cup": "Far from home and tied to their team, fans gravitate to familiar cuisine.",
        "signals": ["aggregate non-English demand", "cuisine-specific Trends ('authentic tacos')", "menu-view surge"],
        "actions": ["feature signature/home-cuisine dishes", "match-day special tied to the fixture", "bilingual menu"],
        "metrics": ["menu_clicks", "order_clicks", "reservation_clicks"],
        "needs": ["mexican_restaurant", "italian_restaurant", "vietnamese_restaurant"],
    },
    {
        "id": "post_match_celebration",
        "label": "Post-match celebration seeker",
        "seeks": "Drinks, shareables, late kitchen, watch-party atmosphere after the final whistle.",
        "why_world_cup": "Evening kickoff creates a post-match food/drink wave.",
        "signals": ["evening kickoff", "'watch party' / 'bar' Trends", "post-window call/reservation surge"],
        "actions": ["set special hours into the late wave", "shareable/group menu", "promote watch-party seating"],
        "metrics": ["reservation_clicks", "call_clicks", "menu_clicks"],
        "needs": ["sports_bar", "bar", "mexican_restaurant", "american_restaurant"],
    },
    {
        "id": "family_group_dining",
        "label": "Family / group dining seeker",
        "seeks": "Group tables, fast ordering, bundles, kid-friendly, card acceptance.",
        "why_world_cup": "Aggregate party-mix skews family/group for many matches.",
        "signals": ["aggregate family+group party share", "reservation-click surge", "large-party menu views"],
        "actions": ["group bundle/prix fixe", "reservation link", "extra seating turns"],
        "metrics": ["reservation_clicks", "order_value", "menu_clicks"],
        "needs": ["mexican_restaurant", "italian_restaurant", "american_restaurant", "vietnamese_restaurant"],
    },
    {
        "id": "local_authenticity_seeker",
        "label": "Local-authenticity seeker",
        "seeks": "Real local favorites, historic/family-owned spots, food culture — not chains.",
        "why_world_cup": "Food tourism: travelers want authentic local experiences and to support locals.",
        "signals": ["'local' / 'authentic' / 'best' Trends", "high-rating local-favorite attention", "save/share clicks"],
        "actions": ["lead with story/heritage on profile", "tag local-favorite categories", "feature signature dishes"],
        "metrics": ["save_clicks", "direction_clicks", "menu_clicks"],
        "needs": ["mexican_restaurant", "italian_restaurant", "vietnamese_restaurant", "cafe", "bar"],
    },
    {
        "id": "last_minute_parking_transit",
        "label": "Last-minute parking / transit seeker",
        "seeks": "Certainty on parking/transit — price, walk time, one-tap reserve/directions.",
        "why_world_cup": "Arrival anxiety peaks 1-3h pre-kickoff around the venue.",
        "signals": ["'parking near' / 'VTA' Trends", "direction-click surge", "near-venue category attention"],
        "actions": ["surface live availability + walk time", "one-tap reserve/directions", "transit-node landing page"],
        "metrics": ["direction_clicks", "reservation_clicks"],
        "needs": ["parking", "parking_lot"],
    },
    {
        "id": "late_night_food",
        "label": "Late-night food seeker",
        "seeks": "Somewhere open after the game for food on the way home.",
        "why_world_cup": "Post-match + transit return creates a late-night demand tail.",
        "signals": ["'late night food' Trends", "late-hour session share", "closes-before-wave gap"],
        "actions": ["extend close past the post-match wave", "late-night menu", "promote 'open late' GBP post"],
        "metrics": ["direction_clicks", "order_clicks"],
        "needs": ["mexican_restaurant", "convenience_store", "fast_food_restaurant", "sports_bar", "cafe"],
    },
]


# visitor-facing recommendation per intent (what we'd tell a fan)
VISITOR_RECO = {
    "convenience_seeker": "Quick, close, open-now spots on your walk to the stadium.",
    "trust_under_uncertainty": "Highly-rated places with recent reviews and clear photos.",
    "language_comfort_seeker": "Places with menus & service in your language.",
    "familiar_food_seeker": "Authentic local spots serving the food you came for.",
    "post_match_celebration": "Bars & late kitchens with watch-party energy after the whistle.",
    "family_group_dining": "Group-friendly tables with fast ordering and bundles.",
    "local_authenticity_seeker": "Neighborhood favorites locals love — not chains.",
    "last_minute_parking_transit": "Parking with walk time + one-tap directions near the venue.",
    "late_night_food": "Open-late spots for food on the way home.",
}


def _level(score: float, first_party: bool) -> tuple[str, str]:
    """Map an evidence score to (confidence_level, status). HIGH needs first-party data."""
    if score >= 0.6 and first_party:
        return "high", "confirmed by signals"
    if score >= 0.6:
        return "medium", "strong ambient signal — connect GA4/GBP to confirm"
    if score >= 0.33:
        return "medium", "emerging signal"
    if score > 0:
        return "low", "weak signal — monitor"
    return "low", "hypothesis — no signal yet"


def _trend_hit(trends: dict, *subs: str) -> float:
    vals = [v for k, v in (trends or {}).items() if any(s in k.lower() for s in subs)]
    return (max(vals) / 100.0) if vals else 0.0


def _evaluate(hyp: dict, ctx: dict) -> tuple[list[dict], float]:
    """Return (evidence, score 0..1) for one hypothesis from the available signals."""
    sig, mix, ev, biz = ctx["sig"], ctx["mix"], ctx["event"], ctx["biz"]
    avail = sig.get("available")
    deltas = sig.get("deltas", {}) if avail else {}
    trends = sig.get("trends", {}) if avail else (ctx.get("ambient_trends") or {})

    def d(key):  # delta pct as 0..1 strength (capped at +200% => 1.0)
        dp = (deltas.get(key) or {}).get("delta_pct")
        return min(max((dp or 0) / 200.0, 0.0), 1.0)

    try:
        kickoff_h = int((ev or {}).get("kickoff_local", "T18")[11:13])
    except Exception:
        kickoff_h = 18
    party = (mix or {}).get("party_mix", {})
    lang = {l["lang"]: l["share"] for l in (mix or {}).get("language_mix", [])}
    ev_pieces: list[dict] = []
    parts: list[float] = []

    def add(label, observed, strength):
        ev_pieces.append({"signal": label, "observed": observed, "supports": strength > 0.05})
        parts.append(strength)

    hid = hyp["id"]
    if hid == "convenience_seeker":
        add("sessions surge", deltas.get("sessions"), d("sessions"))
        add("direction-click surge", deltas.get("direction_clicks"), d("direction_clicks"))
        add("'food near' Trends", None, _trend_hit(trends, "near", "food near"))
    elif hid == "trust_under_uncertainty":
        add("menu-view surge", deltas.get("menu_clicks"), d("menu_clicks"))
        add("rating/review base", f"{biz.get('rating')}* ({biz.get('reviews')})",
            min(((biz.get("reviews") or 0) / 1000.0), 1.0) * (1 if (biz.get("rating") or 0) >= 4.4 else 0.5))
    elif hid == "language_comfort_seeker":
        es = sig.get("es_session_ratio", {}) if avail else {}
        es_win = es.get("match_window") or 0
        es_ratio = es.get("ratio") or 0
        add("non-English session ratio", es, min(es_win / 0.4, 1.0) if es_win else 0.0)
        add("non-English session growth", f"x{es_ratio}", min((es_ratio - 1) / 4.0, 1.0) if es_ratio else 0.0)
        add("non-English aggregate demand", lang, min(sum(v for k, v in lang.items() if k != "en") / 0.5, 1.0))
        add("non-English keyword Trends", None, _trend_hit(trends, "comida", "cerca", "estadio"))
    elif hid == "familiar_food_seeker":
        add("non-English aggregate demand", lang, min(sum(v for k, v in lang.items() if k != "en") / 0.5, 1.0))
        add("cuisine Trends", None, _trend_hit(trends, "taco", "authentic", "comida", "tacos"))
        add("menu-view surge", deltas.get("menu_clicks"), d("menu_clicks"))
    elif hid == "post_match_celebration":
        add("evening kickoff", f"{kickoff_h}:00", 1.0 if kickoff_h >= 16 else 0.2)
        add("'watch party'/'bar' Trends", None, _trend_hit(trends, "watch party", "bar"))
        add("post-window reservation surge", deltas.get("reservation_clicks"), d("reservation_clicks"))
    elif hid == "family_group_dining":
        share = (party.get("family", 0) + party.get("group", 0))
        add("aggregate family+group share", f"{round(share*100)}%", min(share / 0.7, 1.0))
        add("reservation-click surge", deltas.get("reservation_clicks"), d("reservation_clicks"))
    elif hid == "local_authenticity_seeker":
        tags = set(biz.get("local_tags", []))
        add("'local'/'authentic'/'best' Trends", None, _trend_hit(trends, "local", "authentic", "best"))
        add("local-favorite signals", list(tags), min(len(tags) / 3.0, 1.0))
    elif hid == "last_minute_parking_transit":
        add("'parking'/'VTA' Trends", None, _trend_hit(trends, "parking", "vta", "transit"))
        add("direction-click surge", deltas.get("direction_clicks"), d("direction_clicks"))
    elif hid == "late_night_food":
        add("'late night food' Trends", None, _trend_hit(trends, "late night", "after the game"))
        add("evening kickoff (late tail)", f"{kickoff_h}:00", 0.7 if kickoff_h >= 16 else 0.1)

    score = round(sum(parts) / len(parts), 3) if parts else 0.0
    return ev_pieces, score


def _business_fit(hyp: dict, biz: dict) -> bool:
    if not hyp.get("needs"):
        return True
    cat = biz.get("category", "")
    return cat in hyp["needs"] or bool(set(biz.get("secondary_categories", [])) & set(hyp["needs"]))


def learn_visitor_intents(match_id: str, business_id: str = "") -> dict:
    """Score every visitor-intent hypothesis from the available signals.

    Returns intents ranked by evidence, each with confidence + the evidence behind it,
    plus what we're still unsure about. This is 'learn from data', not 'assume identity'.
    """
    sig = get_visitor_signals(business_id, match_id) if business_id else {"available": False}
    mix = mongo.get_source_market_mix(match_id) or {}
    ev = mongo.get_event(match_id) or {}
    biz = mongo.get_business(business_id) or {}
    first_party = bool(sig.get("available"))

    # ambient (non-first-party) trends still available without GA4: from source-market-driven priors.
    ambient_trends = {f"{(ev.get('team_home_name') or '').lower()} watch party": 60} if ev else {}
    ctx = {"sig": sig, "mix": mix, "event": ev, "biz": biz, "ambient_trends": ambient_trends}

    results = []
    for hyp in HYPOTHESES:
        evidence, score = _evaluate(hyp, ctx)
        level, status = _level(score, first_party)
        results.append({
            "id": hyp["id"], "label": hyp["label"], "seeks": hyp["seeks"],
            "why_world_cup": hyp["why_world_cup"],
            "confidence": {"level": level, "score": score, "status": status},
            "evidence": evidence,
            "recommended_actions": hyp["actions"],
            "visitor_recommendation": VISITOR_RECO.get(hyp["id"], ""),
            "metrics_to_watch": hyp["metrics"],
            "business_fit": _business_fit(hyp, biz),
        })
    results.sort(key=lambda r: r["confidence"]["score"], reverse=True)

    unsure = [r["label"] for r in results if r["confidence"]["level"] == "low"]
    return {
        "match_id": match_id, "business_id": business_id,
        "first_party_signals": first_party,
        "signals_summary": {
            "available": first_party,
            "note": sig.get("note"),
            "deltas": sig.get("deltas") if first_party else None,
            "es_session_ratio": sig.get("es_session_ratio") if first_party else None,
        },
        "intents": results,
        "still_unsure_about": unsure,
        "method": "Hypotheses scored from aggregate signals (GA4/GBP/Trends/event/source-market). "
                  "HIGH confidence requires first-party GA4/GBP confirmation. No identity/ethnicity inference.",
    }
