"""Visitor-facing 'home away from home' recommender.

Answers natural questions like: "I'm a Mexico fan near Levi's Stadium, where can I eat
after the match that feels local, welcoming, and easy to get to?" It parses the query
into aggregate, privacy-safe hints (language preference, intent, neighborhood), then
routes the fan to authentic local favorites via the Home-Away-From-Home score.

No identity/ethnicity inference — only language preference the visitor expresses or the
aggregate match context implies.
"""
from __future__ import annotations
from .. import mongo
from .routing import route_local_favorites

# match-team -> likely visitor language preference (aggregate context, not identity)
TEAM_LANG = {"MEX": "es", "ARG": "es", "ESP": "es", "BRA": "pt", "ITA": "it", "FRA": "fr", "POR": "pt"}
LANG_WORDS = {"spanish": "es", "español": "es", "espanol": "es", "portuguese": "pt",
              "português": "pt", "italian": "it", "french": "fr"}
INTENT_WORDS = {
    "after the match": "late_night_food", "after the game": "late_night_food", "late": "late_night_food",
    "parking": "last_minute_parking_transit", "park": "last_minute_parking_transit",
    "family": "family_group_dining", "group": "family_group_dining", "kids": "family_group_dining",
    "watch party": "post_match_celebration", "drinks": "post_match_celebration", "bar": "post_match_celebration",
    "authentic": "local_authenticity_seeker", "local": "local_authenticity_seeker", "historic": "local_authenticity_seeker",
    "coffee": "convenience_seeker", "quick": "convenience_seeker", "tacos": "familiar_food_seeker",
}
NEIGHBORHOOD_WORDS = {
    "downtown": "downtown_san_jose", "san jose": "downtown_san_jose", "san josé": "downtown_san_jose",
    "santana": "santana_row", "santa clara": "santa_clara_central", "levi": "santa_clara_central",
}


def _parse(query: str, event: dict) -> dict:
    q = (query or "").lower()
    langs = [v for k, v in LANG_WORDS.items() if k in q]
    if not langs and event:
        for team in (event.get("team_home"), event.get("team_away")):
            if team in TEAM_LANG:
                langs.append(TEAM_LANG[team])
    intent = next((v for k, v in INTENT_WORDS.items() if k in q), "")
    neighborhood = next((v for k, v in NEIGHBORHOOD_WORDS.items() if k in q), "")
    return {"prefer_langs": sorted(set(langs)), "intent_id": intent, "neighborhood": neighborhood}


def recommend_for_visitor(query: str, match_id: str = "", limit: int = 5) -> dict:
    """Visitor 'home away from home' recommendations from a natural-language ask."""
    # PRIVACY/SAFETY GUARDRAIL parity with plan_visitor_chat: this is BOTH a public endpoint
    # (/api/visitor/recommend) and an agent FunctionTool, so it must refuse identity probes,
    # rank-manipulation, fabrication, injection and underage/impaired-driving asks too — not just
    # the main chat. (Lazy import avoids a circular dep with chat_planner.)
    try:
        from .nlu import analyze
        from .chat_planner import REFUSALS
        _nlu = analyze(query or "")
        _lang = _nlu["response_language"]
        for _flag in ("identity_probe", "underage_alcohol", "impaired_driving",
                      "rank_manipulation", "fabrication_request", "prompt_injection"):
            if _flag in _nlu["guardrail_flags"]:
                return {"mode": "refusal", "guardrail": _flag, "response_language": _lang,
                        "message": REFUSALS[_flag][_lang], "recommendations": [], "query": query}
    except Exception:
        pass  # guardrail must never itself break the recommender
    ev = mongo.get_event(match_id) or {}
    p = _parse(query, ev)
    # neighborhood is a soft preference (proximity is already in the Home score), so we
    # rank across all corridors rather than hard-filtering out nearby favorites.
    routed = route_local_favorites(query=query, neighborhood="", match_id=match_id,
                                   intent_id=p["intent_id"], prefer_langs=p["prefer_langs"], limit=limit)
    cards = []
    for r in routed["results"]:
        reasons = list(r.get("why_recommended", []))
        cards.append({
            "name": r["name"], "category": r["category"],
            "rating": r["rating"], "reviews": r["reviews"], "distance_km": r["distance_km"],
            "home_score": r["home_score"], "badges": r["badges"],
            "feels_like_home_because": reasons[:4] or ["nearby and well-rated"],
            "languages": r["languages"],
        })
    headline = "Local favorites that feel like home"
    if p["prefer_langs"]:
        headline += f" (incl. {'/'.join(p['prefer_langs'])}-friendly)"
    return {
        "query": query, "match_id": match_id, "parsed": p,
        "headline": headline, "recommendations": cards,
        "framing": routed["framing"],
        "privacy_note": "Language preference is taken from your words or aggregate match context — "
                        "we never infer ethnicity or identity.",
    }
