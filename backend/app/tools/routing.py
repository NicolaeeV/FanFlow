"""Local-economy routing — rank nearby businesses for a visitor using the
Home-Away-From-Home score. Deliberately surfaces authentic local favorites over
national chains, while still respecting usefulness (trust, distance, open-now,
language clarity, readiness). NOT pay-to-rank, NOT identity targeting.
"""
from __future__ import annotations
from .. import mongo
from .home_score import home_away_score
from .visitor_intent_learning import HYPOTHESES


def route_local_favorites(query: str = "", neighborhood: str = "", match_id: str = "",
                          intent_id: str = "", prefer_langs: list | None = None, limit: int = 6) -> dict:
    businesses = mongo.get_businesses(neighborhood or None)
    ev = mongo.get_event(match_id) if match_id else {}
    mix = mongo.get_source_market_mix(match_id) if match_id else {}
    demand_langs = {l["lang"] for l in (mix or {}).get("language_mix", [])
                    if l["lang"] not in ("en", "other") and l.get("share", 0) >= 0.1} | set(prefer_langs or [])

    intent_needs = []
    if intent_id:
        for hyp in HYPOTHESES:
            if hyp["id"] == intent_id:
                intent_needs = hyp.get("needs", [])

    ranked = []
    for biz in businesses:
        h = home_away_score(biz, ev or {}, demand_langs, query, intent_needs)
        cls = h["classification"]
        ranked.append({
            "business_id": h["business_id"], "name": h["name"],
            "category": biz.get("category"), "rating": biz.get("rating"), "reviews": biz.get("reviews"),
            "distance_km": h["distance_km"], "home_score": h["home_score"],
            "components": h["components"],
            "badges": cls["labels"],
            "languages": sorted(set(biz.get("languages_supported", ["en"]))),
            "why_recommended": h["why_recommended"],
        })
    ranked.sort(key=lambda x: x["home_score"], reverse=True)
    return {
        "query": query, "neighborhood": neighborhood, "match_id": match_id,
        "results": ranked[:limit],
        "framing": "Authentic local places that feel like home near your match route — "
                   "ranked on trust, convenience, comfort, authenticity, readiness, and clarity, "
                   "with a deliberate boost for local favorites over national chains.",
    }
