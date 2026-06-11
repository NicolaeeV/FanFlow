"""get_business_profile — the live Google API call in the MVP.

Pulls category, rating, reviews, hours, photos, attributes, and location from the
Google Maps Places API. Falls back to the seeded business doc if no key is set.
"""
from __future__ import annotations
from ..config import GOOGLE_MAPS_API_KEY, HAS_MAPS
from .. import mongo


def _gbp_gaps(detail: dict) -> list[str]:
    gaps = []
    if not detail.get("website"):
        gaps.append("missing_website")
    if (detail.get("photos") or 0) < 10:
        gaps.append("few_photos")
    if not detail.get("reservation_link"):
        gaps.append("missing_reservation_link")
    return gaps


def get_business_profile(place_id: str = "", business_id: str = "") -> dict:
    """Return a normalized business profile.

    Pass a Google `place_id` for a live lookup, or a seeded `business_id` for the demo.
    """
    # Brittleness guard: with neither a place_id nor a business_id there is nothing to look up.
    # Don't hand an empty place_id to the live API (it raises a raw ApiError that would crash the
    # agent mid-turn) — return an honest, fast error the model can act on.
    if not place_id and not business_id:
        return {"error": "missing_place_id_and_business_id",
                "detail": "pass a Google place_id for a live lookup or a seeded business_id"}

    # Demo path / no key: use the seeded business document.
    if business_id and (not HAS_MAPS or not place_id):
        biz = mongo.get_business(business_id)
        if biz:
            biz = {k: v for k, v in biz.items() if k != "embedding"}
            biz["source"] = "seed"
            return biz

    if not HAS_MAPS:
        return {"error": "no_maps_key_and_no_seed", "place_id": place_id, "business_id": business_id}

    import googlemaps
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
    fields = ["name", "type", "rating", "user_ratings_total", "opening_hours",
              "formatted_address", "geometry", "website", "url", "photo",
              "price_level", "business_status"]
    # A hallucinated / malformed place_id makes the live API raise (ApiError: INVALID_REQUEST /
    # NOT_FOUND). Catch it: fall back to the seeded doc if a business_id was given, else a clean
    # error dict — the agent degrades gracefully instead of crashing.
    try:
        resp = gmaps.place(place_id=place_id, fields=fields)
    except Exception as e:
        if business_id:
            biz = mongo.get_business(business_id)
            if biz:
                biz = {k: v for k, v in biz.items() if k != "embedding"}
                biz["source"] = "seed"
                return biz
        return {"error": "place_lookup_failed", "place_id": place_id,
                "business_id": business_id, "detail": str(e)[:120]}
    r = resp.get("result", {})
    profile = {
        "google_place_id": place_id,
        "name": r.get("name"),
        "category": (r.get("types") or ["establishment"])[0],
        "secondary_categories": (r.get("types") or [])[1:4],
        "rating": r.get("rating"),
        "reviews": r.get("user_ratings_total"),
        "price_level": r.get("price_level"),
        "lat": r.get("geometry", {}).get("location", {}).get("lat"),
        "lon": r.get("geometry", {}).get("location", {}).get("lng"),
        "address": r.get("formatted_address"),
        "website": r.get("website", ""),
        "hours": r.get("opening_hours", {}).get("weekday_text", []),
        "photos": len(r.get("photos", []) or []),
        "business_status": r.get("business_status"),
        "source": "places_live",
    }
    profile["gbp_gaps"] = _gbp_gaps(profile)
    return profile
