"""Seed MongoDB Atlas with events, source-market mix, and businesses (+ embeddings).

Usage:
    python -m backend.seed.seed_atlas                 # seed from local JSON + embeddings
    python -m backend.seed.seed_atlas --places        # ALSO do one live Places pull near Levi's

Requires MONGODB_URI. The --places flag requires GOOGLE_MAPS_API_KEY and is the
single 'live API call' showcased in the MVP (it geo-searches real businesses near the
venue/spillover neighborhoods and upserts them).
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backend.app import mongo  # noqa: E402
from backend.app.config import HAS_MONGO, HAS_MAPS, GOOGLE_MAPS_API_KEY  # noqa: E402
from backend.app.tools.recommend import embed_text  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parent / "data"

# Match-route corridors: venue, transit nodes, hotel clusters, and spillover districts.
PLACES_ANCHORS = [
    {"neighborhood_id": "santa_clara_central", "lat": 37.3541, "lon": -121.9552},   # near Levi's + Great America station
    {"neighborhood_id": "downtown_san_jose", "lat": 37.3352, "lon": -121.8890},     # VTA/Caltrain hub
    {"neighborhood_id": "santana_row", "lat": 37.3210, "lon": -121.9482},           # Santana Row / Valley Fair
    {"neighborhood_id": "japantown_san_jose", "lat": 37.3489, "lon": -121.8940},    # cultural corridor
    {"neighborhood_id": "mountain_view_castro", "lat": 37.3947, "lon": -122.0797},  # Caltrain feeder + Castro St
    {"neighborhood_id": "sunnyvale_downtown", "lat": 37.3782, "lon": -122.0301},    # hotel/feeder corridor
]
# Dense, match-adjacent types — tight radius (these are everywhere near the corridors).
PLACES_TYPES = ["restaurant", "bar", "cafe", "convenience_store", "parking"]
# Broader-net types fans actually use on match day (delis, markets, bakeries, hotels, gas).
# Pulled with a wider radius because they're sparser than restaurants — this is what lets a
# neighborhood market/deli (sells sandwiches + prepared food) enter the candidate pool.
PLACES_TYPES_WIDE = [
    "grocery_store", "supermarket", "liquor_store", "bakery", "sandwich_shop",
    "meal_takeaway", "gas_station", "lodging", "pharmacy", "shopping_mall",
    "tourist_attraction",
]

# Levi's Stadium (host venue) — center of the full-area grid sweep.
LEVIS = (37.4033, -121.9694)
# Every type we tile across the grid for FULL neighborhood coverage. rankby=distance returns the
# ~20 NEAREST of each type to each grid point, so small local spots (not just prominent chains)
# get captured when the grid is dense enough.
GRID_TYPES = [
    "restaurant", "meal_takeaway", "cafe", "bar", "bakery", "grocery_store", "supermarket",
    "convenience_store", "liquor_store", "lodging", "parking", "gas_station", "pharmacy",
    "shopping_mall", "tourist_attraction", "store",
]


def _load(name):
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


def _embed_business(b: dict) -> list[float]:
    text = " ".join(str(x) for x in [
        b.get("name"), b.get("category"), " ".join(b.get("secondary_categories", [])),
        f"rating {b.get('rating')}", b.get("neighborhood_id"),
    ])
    return embed_text(text)


def seed_static():
    if not HAS_MONGO:
        print("No MONGODB_URI set — nothing to seed. (App will run from local JSON fallbacks.)")
        return
    d = mongo.db()
    d.events.delete_many({}); d.events.insert_many(_load("events.json"))
    d.source_market_mix.delete_many({}); d.source_market_mix.insert_many(_load("source_market_mix.json"))
    d.intent_signals.delete_many({}); d.intent_signals.insert_many(_load("intent_signals.json"))
    d.fan_venues.delete_many({}); d.fan_venues.insert_many(_load("fan_venues.json"))
    d.reviews.delete_many({}); d.reviews.insert_many(_load("reviews.json"))

    biz = _load("businesses_fallback.json")
    for b in biz:
        b["embedding"] = _embed_business(b)
    for b in biz:
        d.businesses.replace_one({"_id": b["_id"]}, b, upsert=True)
    print(f"Seeded {d.events.count_documents({})} events, "
          f"{d.source_market_mix.count_documents({})} market-mix, "
          f"{len(biz)} fallback businesses (with embeddings).")
    print("\nNEXT: create an Atlas Vector Search index named per ATLAS_VECTOR_INDEX on "
          "`businesses.embedding` (cosine). See README for the index JSON.")


def _upsert_nearby(gmaps, d, anchor, place_type, radius, cap, seen):
    """Pull one (anchor, type) Nearby search and upsert up to `cap` real businesses.

    Stores the richer field set we actually use downstream: primary + secondary Google
    types (so a market that also serves prepared food keeps that signal), name, geo, rating,
    reviews, price level. Returns the number of NEW (not previously seen this run) upserts.
    """
    res = gmaps.places_nearby(location=(anchor["lat"], anchor["lon"]),
                              radius=radius, type=place_type)
    n = 0
    for r in res.get("results", [])[:cap]:
        bid = f"biz_{r['place_id'][:18]}"
        if bid in seen:
            continue  # same place surfaced by another anchor/type — keep the first hit
        seen.add(bid)
        loc = r.get("geometry", {}).get("location", {})
        b = {
            "_id": bid,
            "google_place_id": r["place_id"],
            "name": r.get("name"),
            "category": (r.get("types") or [place_type])[0],
            "secondary_categories": (r.get("types") or [])[1:6],
            "lat": loc.get("lat"), "lon": loc.get("lng"),
            "neighborhood_id": anchor["neighborhood_id"],
            "rating": r.get("rating"), "reviews": r.get("user_ratings_total"),
            "price_level": r.get("price_level"),
            "business_status": (r.get("business_status") or "OPERATIONAL").lower().replace("operational", "operational"),
            "gbp": {"missing": []},
            "owner_uid": "user_demo",
            "source": "places_live",
        }
        b["embedding"] = _embed_business(b)
        d.businesses.replace_one({"_id": b["_id"]}, b, upsert=True)
        n += 1
    return n


def seed_places_live():
    if not (HAS_MONGO and HAS_MAPS):
        print("Need MONGODB_URI and GOOGLE_MAPS_API_KEY for --places.")
        return
    import googlemaps
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
    d = mongo.db()
    upserts = 0
    seen: set[str] = set()
    for anchor in PLACES_ANCHORS:
        for t in PLACES_TYPES:           # dense types — tight radius
            upserts += _upsert_nearby(gmaps, d, anchor, t, radius=900, cap=6, seen=seen)
        for t in PLACES_TYPES_WIDE:      # sparse retail/food/lodging — wider net
            upserts += _upsert_nearby(gmaps, d, anchor, t, radius=5000, cap=8, seen=seen)
    print(f"Live Places pull: upserted {upserts} businesses near Levi's Stadium spillover zones "
          f"(types: {len(PLACES_TYPES) + len(PLACES_TYPES_WIDE)}).")


def _grid_points(center, radius_km, spacing_km):
    """Grid of (lat, lon) tiling a circle of `radius_km` around `center`, spaced `spacing_km`."""
    import math
    clat, clon = center
    dlat = spacing_km / 110.574
    steps = int(radius_km / spacing_km) + 1
    pts = []
    for i in range(-steps, steps + 1):
        lat = clat + i * dlat
        dlon = spacing_km / (111.320 * math.cos(math.radians(lat)) or 1e-6)
        for j in range(-steps, steps + 1):
            lon = clon + j * dlon
            d = _haversine_km(clat, clon, lat, lon)
            if d <= radius_km:
                pts.append((round(lat, 5), round(lon, 5)))
    return pts


def _haversine_km(lat1, lon1, lat2, lon2):
    import math
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _nearest_neighborhood(lat, lon):
    """Tag a grid hit with the closest known neighborhood centroid (for vicinity reasoning)."""
    best, bd = None, 1e9
    for a in PLACES_ANCHORS:
        d = _haversine_km(lat, lon, a["lat"], a["lon"])
        if d < bd:
            best, bd = a["neighborhood_id"], d
    return best


def seed_places_grid(radius_mi=15.0, spacing_km=4.0, types=None, est_only=False):
    """FULL-AREA discovery: tile a grid across a `radius_mi` circle around Levi's Stadium and pull
    the ~20 nearest businesses of each type at each grid point (rankby=distance, so small local
    spots are captured — not only prominent chains). Idempotent upserts; dedupes by place_id."""
    if not (HAS_MONGO and HAS_MAPS):
        print("Need MONGODB_URI and GOOGLE_MAPS_API_KEY for --grid.")
        return
    types = types or GRID_TYPES
    radius_km = radius_mi * 1.60934
    pts = _grid_points(LEVIS, radius_km, spacing_km)
    total_calls = len(pts) * len(types)
    print(f"Grid sweep: {len(pts)} grid points × {len(types)} types = ~{total_calls} Nearby calls "
          f"(radius {radius_mi}mi / {radius_km:.0f}km, spacing {spacing_km}km).")
    if est_only:
        return
    import googlemaps, time
    from pymongo import UpdateOne
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
    d = mongo.db()
    seen: set[str] = set()
    upserts = 0
    batch: list = []

    def _flush():
        """Write accumulated upserts in ONE bulk round-trip, then breathe. Batching + pauses
        keep the op-rate well under what a shared (M0) Atlas tier can take — the unbatched
        12k-individual-write pattern is what overwhelmed the cluster last run."""
        nonlocal batch, upserts
        if not batch:
            return
        try:
            d.businesses.bulk_write(batch, ordered=False)
            upserts += len(batch)
        except Exception as e:
            print(f"  (bulk_write retry after error: {str(e)[:60]})")
            time.sleep(5)
            try:
                d.businesses.bulk_write(batch, ordered=False); upserts += len(batch)
            except Exception:
                pass
        batch = []
        time.sleep(1.0)            # gentle pacing between batches (M0-safe)

    for n, (lat, lon) in enumerate(pts, 1):
        nb = _nearest_neighborhood(lat, lon)
        for t in types:
            try:
                res = gmaps.places_nearby(location=(lat, lon), rank_by="distance", type=t)
            except Exception:
                continue
            for r in res.get("results", []):
                bid = f"biz_{r['place_id'][:18]}"
                if bid in seen:
                    continue
                seen.add(bid)
                loc = r.get("geometry", {}).get("location", {})
                # $set only the basic discovery fields (refreshes rating/reviews on re-run) and
                # $setOnInsert the immutable bits — so an UpdateOne over an already-ENRICHED doc
                # refreshes basics WITHOUT wiping website/hours/editorial/photos/places_enriched_at/
                # embedding. (ReplaceOne previously clobbered enrichment on overlap.)
                basic = {
                    "google_place_id": r["place_id"], "name": r.get("name"),
                    "category": (r.get("types") or [t])[0],
                    "secondary_categories": (r.get("types") or [])[1:6],
                    "lat": loc.get("lat"), "lon": loc.get("lng"), "neighborhood_id": nb,
                    "rating": r.get("rating"), "reviews": r.get("user_ratings_total"),
                    "price_level": r.get("price_level"),
                    "business_status": (r.get("business_status") or "OPERATIONAL").lower(),
                }
                # NO embedding at discovery — a 1536-float vector is ~12KB/doc and 12k of them is
                # ~144MB of writes, which is what overwhelmed M0. Embeddings are added later, only
                # for the enriched (matchday-relevant) subset that vector search actually needs.
                batch.append(UpdateOne(
                    {"_id": bid},
                    {"$set": basic,
                     "$setOnInsert": {"owner_uid": "user_demo", "source": "places_live",
                                      "gbp": {"missing": []}}},
                    upsert=True))
                if len(batch) >= 50:          # small batches keep M0 write-spikes in check
                    _flush()
        if n % 20 == 0:
            _flush()
            print(f"  …{n}/{len(pts)} grid points, {upserts} unique businesses so far")
    _flush()
    print(f"Grid sweep done: {upserts} unique businesses across {radius_mi}mi radius.")


# Cuisine / keyword terms the type-based nearest-20 sweep under-samples — small ethnic & local
# eateries (e.g. a neighborhood Chinese spot like "Little Chef") that get crowded out by chains
# in a generic "restaurant" search. Text Search finds them by query.
TEXT_TERMS = [
    "chinese restaurant", "dim sum", "vietnamese restaurant", "pho", "banh mi", "korean restaurant",
    "korean bbq", "japanese restaurant", "ramen", "sushi", "thai restaurant", "indian restaurant",
    "halal food", "filipino restaurant", "ethiopian restaurant", "mexican restaurant", "taqueria",
    "pupuseria", "peruvian restaurant", "mediterranean restaurant", "middle eastern restaurant",
    "deli", "sandwich shop", "family restaurant", "hole in the wall restaurant", "soul food",
    "bbq restaurant", "noodle house", "dumplings",
]


def seed_text_search(terms=None, radius=6000, extra_queries=None):
    """Text-Search sweep for cuisine/keyword terms across the corridors — captures small local &
    ethnic eateries the generic nearest-20 type sweep misses. Upserts THIN docs (no embedding),
    batched + paced for M0 safety; enrichment fills profiles + reviews afterward."""
    if not (HAS_MONGO and HAS_MAPS):
        print("Need MONGODB_URI and GOOGLE_MAPS_API_KEY for --text.")
        return
    import googlemaps, time
    from pymongo import UpdateOne
    terms = terms or TEXT_TERMS
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
    d = mongo.db()
    seen: set[str] = set()
    batch: list = []
    upserts = 0

    def _flush():
        nonlocal batch, upserts
        if not batch:
            return
        try:
            d.businesses.bulk_write(batch, ordered=False); upserts += len(batch)
        except Exception as e:
            print(f"  (bulk_write retry: {str(e)[:50]})"); time.sleep(5)
            try:
                d.businesses.bulk_write(batch, ordered=False); upserts += len(batch)
            except Exception:
                pass
        batch = []
        time.sleep(0.8)

    queries = [(q, a) for q in terms for a in PLACES_ANCHORS] + [(q, None) for q in (extra_queries or [])]
    for n, (term, anchor) in enumerate(queries, 1):
        try:
            kw = dict(query=term)
            if anchor:
                kw.update(location=(anchor["lat"], anchor["lon"]), radius=radius)
            res = gmaps.places(**kw)
        except Exception:
            continue
        nb = anchor["neighborhood_id"] if anchor else "downtown_san_jose"
        for r in res.get("results", []):
            pid = r.get("place_id")
            if not pid:
                continue
            bid = f"biz_{pid[:18]}"
            if bid in seen:
                continue
            seen.add(bid)
            loc = r.get("geometry", {}).get("location", {})
            basic = {
                "google_place_id": pid, "name": r.get("name"),
                "category": (r.get("types") or ["restaurant"])[0],
                "secondary_categories": (r.get("types") or [])[1:6],
                "lat": loc.get("lat"), "lon": loc.get("lng"), "neighborhood_id": nb,
                "rating": r.get("rating"), "reviews": r.get("user_ratings_total"),
                "price_level": r.get("price_level"),
                "business_status": (r.get("business_status") or "OPERATIONAL").lower(),
            }
            batch.append(UpdateOne({"_id": bid},
                                   {"$set": basic,
                                    "$setOnInsert": {"owner_uid": "user_demo", "source": "places_text",
                                                     "gbp": {"missing": []}}},
                                   upsert=True))
            if len(batch) >= 50:
                _flush()
        if n % 20 == 0:
            _flush(); print(f"  …{n}/{len(queries)} text queries, {upserts} hits so far")
    _flush()
    print(f"Text-search sweep done: {upserts} businesses (terms: {len(terms)}).")


def enrich_places_live(reenrich=False, limit=None):
    """Fetch full Place Details for stored Google businesses ONCE and persist the rich profile
    (website, hours, photos count, editorial summary, service attributes, secondary types,
    business status) to Atlas — so the app reads real Google data from the store instead of
    re-calling Maps on every request, and the readiness score uses real fields (not defaults).

    By default SKIPS businesses already enriched (have `places_enriched_at`) so re-runs only pay
    for NEW businesses. Pass reenrich=True to refresh everything."""
    if not (HAS_MONGO and HAS_MAPS):
        print("Need MONGODB_URI and GOOGLE_MAPS_API_KEY for --enrich.")
        return
    import time
    from datetime import datetime, timezone
    from backend.app.tools.google_places_connector import get_place_live  # noqa: E402

    d = mongo.db()
    RUNTIME = ("_source", "_freshness", "_live_fields", "_live_open_now")
    q = {"google_place_id": {"$exists": True, "$ne": None}}
    if not reenrich:
        q["places_enriched_at"] = {"$exists": False}    # only NEW businesses
    pending = d.businesses.count_documents(q)
    docs = list(d.businesses.find(q, {"embedding": 0}))
    # BUDGET CAP: when `limit` is set, enrich only the highest-VALUE businesses — those fans
    # actually search on matchday (matchday-relevant category + close to the venue + has a
    # rating). The long tail stays as thin records; this keeps Place Details spend under budget.
    if limit and len(docs) > limit:
        from backend.app.tools.growth_coach import MATCHDAY_RELEVANT
        from backend.app.tools.business_intel import business_kind
        FOOD_KINDS = {"restaurant", "cafe", "bakery", "deli", "bar", "market"}

        def _priority(b):
            # Review-depth enrichment should land on the eateries fans actually choose — a
            # FOOD/drink kind is the dominant signal (so we fetch reviews for taquerias & cafes,
            # not parking lots, even though parking scores 1.0 on matchday-relevance).
            food = 1.0 if business_kind(b) in FOOD_KINDS else 0.0
            rel = MATCHDAY_RELEVANT.get((b.get("category") or "").lower(), 0.4)
            dist = _haversine_km(b.get("lat"), b.get("lon"), LEVIS[0], LEVIS[1]) if b.get("lat") else 30
            prox = 1.0 / (1 + (dist or 30) / 5)
            reviewed = 1 if (b.get("reviews") or 0) >= 10 else 0   # has reviews worth analyzing
            return food * 0.5 + rel * 0.2 + prox * 0.2 + reviewed * 0.1
        docs.sort(key=_priority, reverse=True)
        docs = docs[:limit]
        print(f"Budget cap: enriching the top {limit} (food/drink-prioritized) of {pending} pending.")
    else:
        print(f"Enriching {len(docs)} businesses ({'all' if reenrich else 'new only'})…")
    enriched = unreachable = closed = 0
    for b in docs:
        live = get_place_live(b, force=True)   # one real Place Details (New) call
        got = [f for f in live.get("_live_fields", []) if f]
        if not got:
            unreachable += 1
            continue
        out = {k: v for k, v in live.items() if k not in RUNTIME}
        # profile completeness from REAL fields (not the old always-empty `missing` list)
        website, hours = out.get("website"), out.get("hours")
        photos = out.get("photos") or 0
        editorial, phone = out.get("editorial_summary"), out.get("phone")
        missing = []
        if not website: missing.append("website")
        if not hours: missing.append("hours")
        if photos < 3: missing.append("photos")
        if not editorial: missing.append("description")
        if not phone: missing.append("phone")
        gbp = dict(out.get("gbp") or {})
        gbp["photos"] = photos
        gbp["missing"] = missing
        out["gbp"] = gbp
        out["places_enriched_at"] = datetime.now(timezone.utc).isoformat()
        out["_enriched_fields"] = got
        out["embedding"] = _embed_business(out)
        d.businesses.replace_one({"_id": out["_id"]}, out, upsert=True)
        enriched += 1
        if out.get("business_status") == "closed":
            closed += 1
        time.sleep(0.15)   # be gentle on the Places API AND on M0 write throughput
    print(f"Enriched {enriched} Google businesses with full profiles "
          f"({unreachable} had no live data, {closed} flagged closed).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--places", action="store_true", help="anchor-based live Places pull (6 corridors)")
    ap.add_argument("--grid", action="store_true", help="FULL-AREA grid sweep around the venue")
    ap.add_argument("--radius-mi", type=float, default=15.0, help="grid radius in miles (default 15)")
    ap.add_argument("--grid-km", type=float, default=4.0, help="grid spacing in km (default 4)")
    ap.add_argument("--estimate", action="store_true", help="print grid call estimate, don't run")
    ap.add_argument("--enrich", action="store_true", help="fetch + STORE full Place Details (new only)")
    ap.add_argument("--reenrich", action="store_true", help="re-enrich ALL (refresh existing too)")
    ap.add_argument("--enrich-limit", type=int, default=None,
                    help="cap enrichment to the top-N matchday-relevant businesses (budget control)")
    ap.add_argument("--text", action="store_true", help="Text-Search sweep for cuisine/local terms")
    ap.add_argument("--text-query", action="append", default=[],
                    help="extra specific Text-Search query (repeatable), e.g. 'little chef chinese food san jose'")
    ap.add_argument("--no-static", action="store_true", help="skip re-seeding static collections")
    args = ap.parse_args()
    if not args.no_static:
        seed_static()
    if args.estimate:
        seed_places_grid(args.radius_mi, args.grid_km, est_only=True)
    if args.grid:
        seed_places_grid(args.radius_mi, args.grid_km)
    if args.places:
        seed_places_live()
    if args.text or args.text_query:
        seed_text_search(extra_queries=args.text_query or None)
    if args.grid or args.places or args.enrich or args.reenrich or args.text:
        enrich_places_live(reenrich=args.reenrich, limit=args.enrich_limit)
