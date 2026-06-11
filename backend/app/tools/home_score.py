"""Home-Away-From-Home Score.

Fans are far from home, under time pressure, emotionally tied to their team. They want
a place that feels familiar, trustworthy, convenient, authentic, and easy. This scores
each business on six visitor-centric dimensions, returns a visitor-facing "why we'd send
a fan here", and an owner-facing "how to be chosen more often".

It is a usefulness ranking with a deliberate local-economy tilt — NOT pay-to-rank, and
NOT identity targeting. Comfort uses aggregate language + match-context fit only.
"""
from __future__ import annotations
import math
from ._geo import haversine_km, open_during_window, latest_close_hour
from .classify import classify_business

# Neighborhoods with strong transit access (VTA / Caltrain / ACE / Great America).
TRANSIT_NEIGHBORHOODS = {"downtown_san_jose", "santa_clara_central"}

WEIGHTS = {
    "trust": 0.22, "convenience": 0.20, "comfort": 0.18,
    "authenticity": 0.16, "readiness": 0.14, "safety_clarity": 0.10,
}

# query keyword -> categories, for familiar-food / match-context fit
QUERY_CATS = {
    "taco": ["mexican_restaurant", "taqueria"], "mexican": ["mexican_restaurant", "taqueria"],
    "pho": ["vietnamese_restaurant"], "italian": ["italian_restaurant"], "pasta": ["italian_restaurant"],
    "coffee": ["cafe", "coffee_shop"], "bar": ["sports_bar", "bar"], "beer": ["sports_bar", "bar"],
    "parking": ["parking", "parking_lot"], "late": ["sports_bar", "bar", "mexican_restaurant", "convenience_store"],
    "family": ["mexican_restaurant", "american_restaurant", "italian_restaurant"],
    "watch party": ["sports_bar", "bar"], "drink": ["bar", "sports_bar"], "food": [],
}


def _clamp(x):
    return max(0.0, min(1.0, x))


def home_away_score(biz: dict, event: dict | None = None, demand_langs: set | None = None,
                    query: str = "", intent_needs: list | None = None) -> dict:
    event = event or {}
    demand_langs = demand_langs or set()
    cls = classify_business(biz)
    rating = biz.get("rating") or 3.5
    reviews = biz.get("reviews") or 0
    langs = set(biz.get("languages_supported", ["en"]))
    nb = biz.get("neighborhood_id", "")
    dist = haversine_km(biz.get("lat"), biz.get("lon"), event.get("venue_lat"), event.get("venue_lon")) if event else 6.0

    # query / match-context category fit
    q = (query or "").lower()
    want_cats = set(intent_needs or [])
    for k, v in QUERY_CATS.items():
        if k in q:
            want_cats.update(v)
    cat = biz.get("category", "")
    secs = set(biz.get("secondary_categories", []))
    cat_fit = 1.0 if (not want_cats or cat in want_cats or secs & want_cats) else 0.4

    # 6 dimensions ----------------------------------------------------------
    trust = _clamp((rating / 5) * 0.6 + min(math.log10(reviews + 1) / 3.2, 1) * 0.4)
    near_transit = nb in TRANSIT_NEIGHBORHOODS
    convenience = _clamp(0.7 * (1.2 / (1 + dist / 4)) + (0.3 if near_transit else 0.0)) \
        * (0.6 if open_during_window(biz, event) < 1 else 1.0)
    lang_match = bool((langs & demand_langs) - {"en"})
    comfort = _clamp(0.5 * cat_fit + (0.3 if lang_match else 0.0) + (0.2 if cls["family_group_friendly"] else 0.0))
    authenticity = _clamp(
        (0.5 if cls["is_local_favorite"] else 0.0) + (0.3 if cls["is_historic_cultural"] else 0.0)
        + 0.2 - (0.5 if cls["is_chain"] else 0.0)
    )
    readiness = {"weak": 0.3, "fair": 0.55, "good": 0.8, "strong": 1.0}[cls["conversion_readiness"]]
    if cls["late_night_capable"]:
        readiness = _clamp(readiness + 0.1)
    gbp = biz.get("gbp", {})
    safety_clarity = _clamp(
        (0.4 if biz.get("website") else 0) + (0.3 if biz.get("hours") else 0)
        + (0.3 if (gbp.get("photos", biz.get("photos", 0)) or 0) >= 10 else 0.1)
    )

    comps = {"trust": round(trust, 2), "convenience": round(convenience, 2),
             "comfort": round(comfort, 2), "authenticity": round(authenticity, 2),
             "readiness": round(readiness, 2), "safety_clarity": round(safety_clarity, 2)}
    score = round(100 * sum(comps[k] * WEIGHTS[k] for k in WEIGHTS), 1)

    # visitor-facing "why" -------------------------------------------------
    why = []
    tags = set(biz.get("local_tags", []))
    if cls["is_local_favorite"]: why.append("a neighborhood favorite, not a chain")
    # only claim "historic" when the record actually says so; otherwise "cultural"
    if "historic" in tags: why.append("a historic local spot")
    elif "cultural" in tags: why.append("a cultural local spot")
    if rating >= 4.4 and reviews >= 300: why.append(f"{rating}★ from {reviews}+ reviews")
    if lang_match:
        _names = {"es": "Spanish", "pt": "Portuguese", "it": "Italian", "vi": "Vietnamese",
                  "ar": "Arabic", "fr": "French"}
        _l = sorted((langs & demand_langs) - {"en"})
        why.append(f"{'/'.join(_names.get(x, x) for x in _l)} menu & service")
    if cls["late_night_capable"]: why.append("open late for the post-match wave")
    if near_transit: why.append("easy from VTA/Caltrain")
    if dist <= 8: why.append(f"~{round(dist,1)}km from the stadium")

    # owner-facing "how to be chosen more often" ---------------------------
    improve = []
    if not lang_match and (demand_langs - {"en"}):
        improve.append(f"Add {'/'.join(sorted(demand_langs - {'en'}))} menu/profile copy — that demand is rising")
    if cls["conversion_readiness"] in ("weak", "fair"):
        if not gbp.get("has_menu_link"): improve.append("Add a menu link")
        if not gbp.get("has_reservation_link"): improve.append("Add an order/reservation link")
        if (gbp.get("photos", biz.get("photos", 0)) or 0) < 10: improve.append("Add 10+ recent photos")
    if not cls["late_night_capable"]:
        improve.append("Set match-day special hours into the post-match window")
    if cls["is_local_favorite"] and cls["conversion_readiness"] != "strong":
        improve.append("You're a local favorite but hard to act on — fix the conversion path so tourists choose you")

    return {
        "business_id": biz.get("_id"), "name": biz.get("name"),
        "home_score": score, "components": comps,
        "classification": cls,
        "distance_km": round(dist, 1),
        "why_recommended": why,
        "how_to_improve": improve,
    }
