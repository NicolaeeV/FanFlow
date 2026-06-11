"""Google Visibility Score — how findable & convincing a business is at the moment
tourists search. Built on Google's stated local-ranking factors: relevance,
distance, prominence (reviews/ratings/links), plus completeness, hours, photos,
conversion links, and language/content readiness.

We never claim to buy or guarantee ranking (Google says you can't). We score the
KNOWN, CONTROLLABLE inputs and return concrete fixes.
"""
from __future__ import annotations
import math
from .. import mongo
from ._geo import haversine_km, open_during_window, closes_before

# Categories that match common World Cup match-day searches.
MATCHDAY_RELEVANT = {
    "mexican_restaurant": 1.0, "taqueria": 1.0, "sports_bar": 1.0, "bar": 0.9,
    "fast_food_restaurant": 0.9, "cafe": 0.8, "coffee_shop": 0.8, "parking": 1.0,
    "parking_lot": 1.0, "convenience_store": 0.85, "american_restaurant": 0.8,
    "italian_restaurant": 0.75, "vietnamese_restaurant": 0.7, "grocery": 0.6,
}

WEIGHTS = {
    "completeness": 0.16, "rating_reviews": 0.20, "distance_to_flow": 0.16,
    "category_relevance": 0.12, "hours_match": 0.10, "photo_menu": 0.10,
    "conversion_links": 0.08, "language_content": 0.08,
}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_visibility_score(business_id: str, match_id: str) -> dict:
    biz = mongo.get_business(business_id) or {}
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    gbp = biz.get("gbp", {})
    missing = set(gbp.get("missing", []))

    # 1. completeness (fewer missing profile elements = better)
    completeness = _clamp(1 - len(missing) / 5)

    # 2. rating & review strength (prominence)
    rating = biz.get("rating") or 3.5
    reviews = biz.get("reviews") or 0
    rating_reviews = _clamp((rating / 5) * 0.6 + min(math.log10(reviews + 1) / 3.2, 1) * 0.4)

    # 3. distance to match-day flow (closer to venue/spillover = more findable)
    dist = haversine_km(biz.get("lat"), biz.get("lon"), ev.get("venue_lat"), ev.get("venue_lon"))
    distance_to_flow = _clamp(1.3 / (1 + dist / 4))  # ~1.0 at venue, decays with km

    # 4. category relevance to match-day searches
    category_relevance = MATCHDAY_RELEVANT.get(biz.get("category", ""), 0.5)

    # 5. hours match (open across the pre+post window?)
    hours_match = open_during_window(biz, ev)

    # 6. photo & menu quality
    photos = gbp.get("photos", biz.get("photos", 0)) or 0
    photo_menu = _clamp(min(photos / 15, 1) * 0.6 + (0.4 if gbp.get("has_menu_link") else 0))

    # 7. conversion links (menu / reservation / website)
    conversion_links = _clamp(
        (0.34 if gbp.get("has_menu_link") else 0)
        + (0.33 if gbp.get("has_reservation_link") else 0)
        + (0.33 if biz.get("website") else 0)
    )

    # 8. language/content readiness vs aggregate demand languages
    demand_langs = {l["lang"]: l["share"] for l in mix.get("language_mix", [])}
    supported = set(biz.get("languages_supported", ["en"]))
    covered = sum(share for lg, share in demand_langs.items() if lg in supported)
    language_content = _clamp(covered)

    comps = {
        "completeness": round(completeness, 2),
        "rating_reviews": round(rating_reviews, 2),
        "distance_to_flow": round(distance_to_flow, 2),
        "category_relevance": round(category_relevance, 2),
        "hours_match": round(hours_match, 2),
        "photo_menu": round(photo_menu, 2),
        "conversion_links": round(conversion_links, 2),
        "language_content": round(language_content, 2),
    }
    score = round(100 * sum(comps[k] * WEIGHTS[k] for k in WEIGHTS), 1)

    # Concrete, controllable fixes (ranked by weighted upside).
    fixes = []
    if "menu_link" in missing or not gbp.get("has_menu_link"):
        fixes.append("Add a menu link to your Google Business Profile")
    if not gbp.get("has_reservation_link"):
        fixes.append("Add a reservation/order link")
    if photos < 10:
        fixes.append("Add 10+ recent, high-quality photos")
    early, close_h = closes_before(biz, ev)
    if early:
        fixes.append(f"Set special hours — you close ~{close_h}:00 and miss the post-match wave")
    unmet = [lg for lg in demand_langs if lg not in supported and lg != "en"]
    if unmet:
        fixes.append(f"Add {'/'.join(unmet)} menu + profile description (aggregate language demand)")
    if "special_hours" in missing:
        fixes.append("Publish match-day special hours")

    return {
        "business_id": business_id, "match_id": match_id,
        "business_name": biz.get("name"),
        "visibility_score": score,
        "components": comps, "weights": WEIGHTS,
        "controllable_fixes": fixes,
        "distance_to_venue_km": round(dist, 1),
        "disclaimer": "Google says local ranking can't be bought or guaranteed. This scores the "
                      "known controllable inputs to relevance, distance, prominence, and conversion.",
    }
