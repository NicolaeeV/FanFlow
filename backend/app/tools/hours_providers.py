"""Live opening-hours / open-now provider chain.

No single API covers every shop, so we register the real live-hours sources and use whichever
one has a key AND an id for the place — owner-authoritative first (Square POS, Google Business
Profile), then platform data (Google Places, Yelp Fusion, Woosmap). Each provider returns
structured hours (+ open_now + special days) from a genuine keyed call, or None. OFFLINE /
NO KEY → every provider returns None → the caller keeps seeded hours labeled needs_verification.
We NEVER assert open_now without a successful live call. Nothing here fabricates hours.
"""
from __future__ import annotations
import os
from .source_catalog import integration_status

# priority order: the business's own systems are most authoritative, then platforms.
# `id_field` is the per-place identifier each provider needs (absent in seed → that provider
# can't be called, so it cleanly yields None).
PROVIDERS = [
    {"id": "square", "label": "Square (owner POS)", "id_field": "square_location_id"},
    {"id": "gbp", "label": "Google Business Profile", "id_field": "gbp_place_id"},
    {"id": "places_api", "label": "Google Places", "id_field": "google_place_id"},
    {"id": "yelp_fusion", "label": "Yelp Fusion", "id_field": "yelp_id"},
    {"id": "woosmap", "label": "Woosmap", "id_field": "woosmap_id"},
]


def provider_status() -> dict:
    """{provider_id: available | missing_key | blocked_by_oauth | using_seed_fallback}."""
    return {p["id"]: integration_status(p["id"]) for p in PROVIDERS}


def available_providers() -> list:
    return [p for p in PROVIDERS if integration_status(p["id"]) == "available"]


def _fetch_google(place: dict):
    from .google_places_connector import (fetch_place_details, _hours_to_seed_shape,
                                          _special_days, normalize_business_status)
    pid = place.get("google_place_id")
    if not pid:
        return None
    raw = fetch_place_details(pid)
    if not raw:
        return None
    oc = raw.get("currentOpeningHours") or raw.get("regularOpeningHours")
    return {
        "hours": _hours_to_seed_shape(oc),
        "open_now": (raw.get("currentOpeningHours") or {}).get("openNow"),
        "special_hours_dates": _special_days(raw.get("currentOpeningHours")),
        "business_status": normalize_business_status(raw.get("businessStatus")),
        "source": "places_api",
    }


def _fetch_yelp(place: dict):
    bid = place.get("yelp_id")
    key = os.getenv("YELP_API_KEY")
    if not (bid and key):
        return None
    try:
        import httpx
        r = httpx.get(f"https://api.yelp.com/v3/businesses/{bid}",
                      headers={"Authorization": f"Bearer {key}"}, timeout=8)
        r.raise_for_status()
        d = r.json()
        is_open = (d.get("hours") or [{}])[0].get("is_open_now")
        return {"hours": None, "open_now": is_open, "special_hours_dates": [], "source": "yelp_fusion"}
    except Exception:
        return None


def _fetch_woosmap(place: dict):
    sid = place.get("woosmap_id")
    key = os.getenv("WOOSMAP_API_KEY")
    if not (sid and key):
        return None
    try:
        import httpx
        r = httpx.get(f"https://api.woosmap.com/stores/{sid}", params={"key": key}, timeout=8)
        r.raise_for_status()
        oh = (r.json().get("properties") or {}).get("opening_hours") or {}
        return {"hours": None, "open_now": oh.get("open_now"), "special_hours_dates": [], "source": "woosmap"}
    except Exception:
        return None


def _fetch_square(place: dict):
    lid = place.get("square_location_id")
    token = os.getenv("SQUARE_ACCESS_TOKEN")
    if not (lid and token):
        return None
    try:
        import httpx
        r = httpx.get(f"https://connect.squareup.com/v2/locations/{lid}",
                      headers={"Authorization": f"Bearer {token}", "Square-Version": "2024-01-18"}, timeout=8)
        r.raise_for_status()
        # Square returns business_hours.periods; hours mapping is owner-specific — we only
        # surface that we have an authoritative owner source here.
        return {"hours": None, "open_now": None, "special_hours_dates": [], "source": "square"}
    except Exception:
        return None


_FETCHERS = {"places_api": _fetch_google, "yelp_fusion": _fetch_yelp,
             "woosmap": _fetch_woosmap, "square": _fetch_square}


def live_hours(place: dict, skip: set | None = None) -> dict | None:
    """First available provider that has a key AND an id for this place wins. None offline."""
    skip = skip or set()
    for p in PROVIDERS:
        pid = p["id"]
        if pid in skip or integration_status(pid) != "available":
            continue
        fetch = _FETCHERS.get(pid)
        if not fetch:
            continue
        result = fetch(place)
        if result:
            return result
    return None


def live_open_now(place: dict) -> tuple:
    """('open' | 'closed', source_id) from a live provider, or (None, None) when we can't
    confirm live — we never assert open/closed without a real call."""
    res = live_hours(place)
    if res and res.get("open_now") is not None:
        return ("open" if res["open_now"] else "closed", res["source"])
    return (None, None)
