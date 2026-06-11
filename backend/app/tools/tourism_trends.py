"""Tourism & shopping-trend signals — PRIVACY-SAFE AGGREGATE PROXIES ONLY.

There is no free API for live foot traffic, and individual visitor tracking / home-origin
inference (e.g. SafeGraph home locations to split "tourists vs locals") is OFF by design — it
violates this product's privacy boundary. Instead we derive a defensible, aggregate proxy from
data we may legally use: category density, chain-vs-independent mix, price level, and the
neighborhood model's character. Every output is labeled an aggregate proxy and a `tourist_zone`
inference (candidate, never fact). "Where locals shop" leans on the independent/local signal,
not on tracking anyone.

Live upgrades (when keyed) plug in here: Google Places Insights (place density), Foursquare
(popularity — candidate), SafeGraph (k-anon aggregate visits ONLY, never origin). Reddit local-
favorite mentions come solely from the official Reddit Data API (candidate, no usernames) —
scrapers (Apify / Bright Data / Pushshift) are prohibited.
"""
from __future__ import annotations
from .. import mongo
from . import neighborhoods as _nb
from .source_catalog import integration_status

DISCLAIMER = ("Aggregate category/price/independence proxy — never individual foot traffic, "
              "never visitor origin or tourist-vs-local-by-home.")

FOODISH = {"mexican_restaurant", "cafe", "american_restaurant", "sandwich_shop",
           "convenience_store", "taqueria", "vietnamese_restaurant", "italian_restaurant",
           "sports_bar", "bar", "fast_food_restaurant", "coffee_shop", "bakery"}

_TOURIST_VIBE = ("stadium", "convention", "hotel", "chain", "great america")
_LOCAL_VIBE = ("local", "family", "cultural", "japantown", "portugal", "neighborhood", "locals", "historic")
# the live trend sources this proxy would upgrade to (status surfaced honestly). Placer.ai is
# the privacy-safer aggregate alternative to raw SafeGraph patterns.
TREND_SOURCES = ["places_insights", "foursquare_api", "placer_ai", "safegraph", "reddit_public_post"]


def _zone_biz(nb_id: str) -> list:
    return [b for b in mongo.get_businesses()
            if b.get("neighborhood_id") == nb_id and b.get("category") in FOODISH]


def zone_shopping_profile(nb_id: str) -> dict:
    """Aggregate proxy for how tourist- vs local-leaning a neighborhood's spots are."""
    biz = _zone_biz(nb_id)
    n = len(biz)
    indie = sum(1 for b in biz if not b.get("chain"))
    chains = n - indie
    indie_share = round(indie / n, 2) if n else None
    vibe = (_nb.get_neighborhood(nb_id) or {}).get("vibe", "").lower()
    tourist_bias = any(w in vibe for w in _TOURIST_VIBE)
    local_bias = any(w in vibe for w in _LOCAL_VIBE)
    if n == 0:
        lean = "unknown"
    else:
        # weighted aggregate proxy: independent share + vibe lean − chain density. A "locals"
        # mention can't override a chain-heavy, stadium/hotel/convention zone.
        score = (indie_share + (0.15 if local_bias else 0) - (0.15 if tourist_bias else 0)
                 - 0.1 * (chains / n))
        lean = "local-leaning" if score >= 0.7 else "tourist-leaning" if score <= 0.45 else "mixed"
    return {
        "neighborhood_id": nb_id,
        "name": (_nb.get_neighborhood(nb_id) or {}).get("name", nb_id),
        "lean": lean, "independent_share": indie_share, "chains": chains, "sample_size": n,
        "source": "aggregate_proxy", "verification_status": "needs_verification",
        "disclaimer": DISCLAIMER,
    }


def zone_profiles() -> list:
    return [zone_shopping_profile(nb) for nb in _nb.NEIGHBORHOODS]


def where_locals_shop(limit: int = 8) -> dict:
    """The anti-tourist-trap list: independent/local spots locals favor, ranked by rating.
    Reputation stays a candidate signal (never asserted fact); chains are excluded."""
    cands = []
    for b in mongo.get_businesses():
        if b.get("category") not in FOODISH or b.get("chain"):
            continue
        cands.append({
            "place_id": b["_id"], "name": b["name"],
            "neighborhood": (_nb.get_neighborhood(b.get("neighborhood_id", "")) or {}).get("name", b.get("neighborhood_id")),
            "rating": b.get("rating"),
            "local_signal": "candidate" if (b.get("local_tags") or []) else "independent",
        })
    cands.sort(key=lambda c: (c["rating"] or 0), reverse=True)
    return {"results": cands[:limit], "source": "aggregate_proxy",
            "note": "Independent local spots (reputation = candidate, verify). " + DISCLAIMER}


def tourist_demand_zones() -> list:
    """For owners: which zones concentrate tourist demand (chain density + stadium/hotel
    adjacency proxy). Aggregate inference, labeled — not visitor tracking."""
    profs = [p for p in zone_profiles() if p["sample_size"]]
    return sorted(profs, key=lambda p: (p["lean"] == "tourist-leaning", p["chains"]), reverse=True)


def origin_inference_allowed() -> bool:
    """Hard NO: we never infer a visitor's home/origin or split tourists-vs-locals by location.
    Kept as an explicit, testable guard on the privacy boundary."""
    return False


def trend_source_status() -> dict:
    """Honest readiness of the live trend upgrades (all aggregate/candidate; SafeGraph origin off)."""
    return {sid: integration_status(sid) for sid in TREND_SOURCES}
