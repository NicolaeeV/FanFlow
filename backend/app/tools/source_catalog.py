"""Source catalog + trust policy (code form).

A structured registry of every data source we may use, each with a trust label, what
claims it can support, caching/storage rules, and licensing/privacy notes. The helpers
enforce the policy: which sources are allowed for a use case, how to label evidence in the
UI, and when a claim still requires verification.

Grounding: availability/terms verified June 2026 (see docs/DATA_SOURCE_INVENTORY.md for
citations). Where terms are unclear/paid/restricted we mark it — we never assume access.
NOTHING here fabricates a source's availability.
"""
from __future__ import annotations

# ── data-quality labels (trust tiers) ─────────────────────────────────────────
VERIFIED_SOURCE = "verified_source"            # we verified it (curated seed, confirmed)
OFFICIAL_SOURCE = "official_source"            # govt/official/operator (NWS, 511, FIFA, city)
BUSINESS_OWNED_SOURCE = "business_owned_source" # the business's own GBP/site/menu (owner-connected)
PLATFORM_SOURCE = "platform_source"            # 3rd-party platform (Places, Yelp, FSQ, OSM, editorial)
PUBLIC_POST_CANDIDATE = "public_post_candidate" # Reddit/social — candidate signal only, never fact
STALE_SOURCE = "stale_source"                  # data too old to trust as-is
NEEDS_VERIFICATION = "needs_verification"      # unknown/insufficient — must verify
PROHIBITED_OR_UNUSABLE = "prohibited_or_unusable"  # ToS/legal block — never use

TRUST_SCORE = {VERIFIED_SOURCE: 0.9, OFFICIAL_SOURCE: 0.9, BUSINESS_OWNED_SOURCE: 0.8,
               PLATFORM_SOURCE: 0.7, PUBLIC_POST_CANDIDATE: 0.35, STALE_SOURCE: 0.3,
               NEEDS_VERIFICATION: 0.4, PROHIBITED_OR_UNUSABLE: 0.0}

UI_LABEL = {VERIFIED_SOURCE: "Verified", OFFICIAL_SOURCE: "Official source",
            BUSINESS_OWNED_SOURCE: "From the business", PLATFORM_SOURCE: "Platform data",
            PUBLIC_POST_CANDIDATE: "Mentioned online — candidate, unverified",
            STALE_SOURCE: "May be out of date — verify", NEEDS_VERIFICATION: "Needs verification",
            PROHIBITED_OR_UNUSABLE: "Not usable"}

# ── the catalog ────────────────────────────────────────────────────────────────
# storable: 'yes' | 'id_only' | 'no' | 'short_ttl' | 'derived_only'
SOURCE_CATALOG: dict[str, dict] = {
    # --- Google ---
    "places_api": {
        "name": "Google Places API (New)", "category": "google", "trust": PLATFORM_SOURCE,
        "free": "per-SKU monthly free caps, then paid ($5–$40/1k)", "key_required": True,
        "allowed_use": ["rating", "hours", "open_now", "category", "geocode", "location",
                        "verified_fact", "hidden_gem"],
        "prohibited_use": ["store_content", "build_competing_db", "mass_copy"],
        "storable": "id_only",  # only place_id may be stored; content fetched live
        "freshness": "live", "attribution": "Google + data-provider + review authors",
        "privacy": "Place content may not be cached except place_id (Maps ToS).",
        "supports": ["rating", "hours", "open_now", "category", "location", "price_level"],
    },
    "gbp": {
        "name": "Google Business Profile + Performance API", "category": "google",
        "trust": BUSINESS_OWNED_SOURCE, "free": "free (access approval required)",
        "key_required": True, "allowed_use": ["hours", "open_now", "menu", "category",
                                              "owner_metrics", "verified_fact"],
        "prohibited_use": ["competitor_metrics", "store_content"], "storable": "derived_only",
        "freshness": "daily (some metrics lag)", "attribution": "Google",
        "privacy": "Only profiles the user owns/manages; OAuth business.manage.",
        "supports": ["hours", "open_now", "menu", "category", "owner_metrics"],
    },
    "ga4": {
        "name": "Google Analytics 4 Data API", "category": "google", "trust": BUSINESS_OWNED_SOURCE,
        "free": "free (token quotas)", "key_required": True,
        "allowed_use": ["owner_metrics", "demand_signal"], "prohibited_use": ["competitor_metrics"],
        "storable": "derived_only", "freshness": "realtime 30min + daily",
        "attribution": "n/a", "privacy": "Owner-authorized property only; aggregate only.",
        "supports": ["owner_metrics", "demand_signal"],
    },
    "routes_api": {
        "name": "Google Routes API (replaces Directions/Distance Matrix)", "category": "google",
        "trust": PLATFORM_SOURCE, "free": "per-SKU free caps, then paid", "key_required": True,
        "allowed_use": ["travel_time", "distance", "route"], "prohibited_use": ["store_content"],
        "storable": "short_ttl",  # lat/lng cache <=30 days; place_id forever
        "freshness": "live", "attribution": "Google", "privacy": "Cache coords <=30 days.",
        "supports": ["travel_time", "distance", "route"],
    },
    "mapbox_matrix": {
        "name": "Mapbox Matrix API (live-traffic travel times)", "category": "maps",
        "trust": PLATFORM_SOURCE, "free": "100k matrix elements/mo free, then $2/1k",
        "key_required": True, "allowed_use": ["travel_time", "distance", "route", "traffic"],
        "prohibited_use": ["store_content"], "storable": "short_ttl",
        "freshness": "live (traffic-aware durations)", "attribution": "© Mapbox © OpenStreetMap",
        "privacy": "send only coordinates.", "supports": ["travel_time", "distance", "traffic"],
    },
    "openrouteservice": {
        "name": "OpenRouteService (OSM routing, no live traffic)", "category": "maps",
        "trust": PLATFORM_SOURCE, "free": "2,000 requests/day free, no credit card",
        "key_required": True, "allowed_use": ["travel_time", "distance", "route"],
        "prohibited_use": ["claim_live_traffic"], "storable": "yes",
        "freshness": "routed estimate (historical/statistical speeds — NOT live traffic)",
        "attribution": "© openrouteservice.org / OpenStreetMap contributors",
        "privacy": "send only coordinates.", "supports": ["travel_time", "distance"],
    },
    "translation_api": {
        "name": "Google Cloud Translation API", "category": "google", "trust": PLATFORM_SOURCE,
        "free": "500k chars/month free, then $20/M", "key_required": True,
        "allowed_use": ["translate", "language_detect"], "prohibited_use": [],
        "storable": "yes", "freshness": "live", "attribution": "Google",
        "privacy": "Send only necessary text.", "supports": ["translate", "language_detect"],
    },
    "trends_official": {
        "name": "Google Trends API (alpha, waitlist)", "category": "google", "trust": PLATFORM_SOURCE,
        "free": "alpha — pricing unconfirmed", "key_required": True,
        "allowed_use": ["demand_signal", "candidate_signal"], "prohibited_use": [],
        "storable": "derived_only", "freshness": "daily", "attribution": "Google",
        "privacy": "Aggregate search interest only.", "supports": ["demand_signal"],
    },
    "trends_pytrends": {
        "name": "pytrends (UNOFFICIAL Trends scraper)", "category": "google",
        "trust": NEEDS_VERIFICATION, "free": "free but ToS-risky / unreliable", "key_required": False,
        "allowed_use": ["candidate_signal"], "prohibited_use": ["production_dependency", "verified_fact"],
        "storable": "derived_only", "freshness": "best-effort",
        "attribution": "n/a", "privacy": "Scrapes Trends endpoints — fragile, rate-limited.",
        "supports": ["candidate_signal"],
    },
    # --- public / official ---
    "nws_weather": {
        "name": "NWS api.weather.gov", "category": "public", "trust": OFFICIAL_SOURCE,
        "free": "free, NO key", "key_required": False,
        "allowed_use": ["weather", "weather_alert"], "prohibited_use": [],
        "storable": "yes", "freshness": "updated multiple times/hour",
        "attribution": "US public domain (set User-Agent)", "privacy": "none",
        "supports": ["weather", "weather_alert"],
    },
    "transit_511": {
        "name": "511 SF Bay (GTFS + GTFS-Realtime: VTA/Caltrain/ACE)", "category": "public",
        "trust": OFFICIAL_SOURCE, "free": "free", "key_required": True,
        "allowed_use": ["transit", "transit_realtime", "route"], "prohibited_use": [],
        "storable": "yes", "freshness": "realtime <90s for RT", "attribution": "511 Data Agreement",
        "privacy": "none", "supports": ["transit", "transit_realtime"],
    },
    "city_open_data": {
        "name": "City/County open data (San José CKAN/ArcGIS, Santa Clara, Socrata)",
        "category": "public", "trust": OFFICIAL_SOURCE, "free": "free", "key_required": False,
        "allowed_use": ["closures", "parking", "permits", "city_events"], "prohibited_use": [],
        "storable": "yes", "freshness": "varies (closures ~weekly)", "attribution": "open data license",
        "privacy": "none", "supports": ["closures", "parking", "city_events"],
    },
    "official_event": {
        "name": "Official event/host-city/FIFA/Levi's/fan-zone pages", "category": "public",
        "trust": OFFICIAL_SOURCE, "free": "free (HTML, no API)", "key_required": False,
        "allowed_use": ["event", "watch_party_event", "schedule", "verified_fact"],
        "prohibited_use": ["mass_scrape"], "storable": "yes",  # facts; curate manually
        "freshness": "manual / event-driven", "attribution": "link to source",
        "privacy": "none", "supports": ["watch_party_event", "event", "schedule"],
    },
    "osm_overpass": {
        "name": "OpenStreetMap / Overpass API", "category": "public", "trust": PLATFORM_SOURCE,
        "free": "free (shared servers throttle)", "key_required": False,
        "allowed_use": ["category", "location", "geocode", "amenity"], "prohibited_use": ["hammer_public_server"],
        "storable": "yes",  # ODbL: share-alike + attribution
        "freshness": "live community edits", "attribution": "© OpenStreetMap contributors (ODbL)",
        "privacy": "none", "supports": ["category", "location", "amenity"],
    },
    "places_insights": {
        "name": "Google Places Insights / Aggregate API (area density)", "category": "google",
        "trust": PLATFORM_SOURCE, "free": "Maps Platform ($200/mo credit)", "key_required": True,
        "allowed_use": ["place_density", "aggregate_count", "demand_signal"],
        "prohibited_use": ["individual_tracking", "store_content"], "storable": "derived_only",
        "freshness": "aggregate (counts/heatmaps, not visitor logs)", "attribution": "Google",
        "privacy": "Aggregate area counts only — NEVER individual visitors.",
        "supports": ["place_density", "aggregate_count"],
    },
    "safegraph": {
        "name": "SafeGraph Patterns (foot-traffic, PAID)", "category": "mobility",
        "trust": PLATFORM_SOURCE, "free": "enterprise (no free tier)", "key_required": True,
        # We permit ONLY k-anonymous aggregate visit counts. Home-origin / tourist-vs-local-by-
        # home / individual device tracking is OFF — it violates our privacy boundary.
        "allowed_use": ["aggregate_visits"],
        "prohibited_use": ["origin_inference", "home_location", "tourist_vs_local_by_origin",
                           "individual_tracking", "unofficial_kaggle_dump"],
        "storable": "derived_only", "freshness": "daily/weekly patterns",
        "attribution": "SafeGraph (licensed)",
        "privacy": "Aggregate visits above k-anonymity ONLY; never device-level or home-origin.",
        "supports": ["aggregate_visits"],
    },
    "flight_arrivals": {
        "name": "Flight arrivals (FlightAPI.io / FlightLabs / Aviation Edge)", "category": "mobility",
        "trust": PLATFORM_SOURCE, "free": "~20-50 calls/day free tiers", "key_required": True,
        # Aggregate flight COUNTS by origin region only — never passenger manifests or PII.
        "allowed_use": ["aggregate_arrivals", "demand_signal"],
        "prohibited_use": ["passenger_manifest", "individual_tracking", "pii"],
        "storable": "derived_only", "freshness": "realtime/15min polling",
        "attribution": "per provider terms",
        "privacy": "Store COUNTS ('N international arrivals from X region'), never passengers.",
        "supports": ["aggregate_arrivals", "demand_signal"],
    },
    "hotel_rates": {
        "name": "Hotel rate/availability (Makcorps / Amadeus Hotel Search)", "category": "mobility",
        "trust": PLATFORM_SOURCE, "free": "trial tiers", "key_required": True,
        # Aggregated rates + room availability per zone — an occupancy PROXY, never guest data.
        "allowed_use": ["occupancy_proxy", "demand_signal"],
        "prohibited_use": ["guest_data", "individual_tracking", "pii"],
        "storable": "derived_only", "freshness": "daily polling",
        "attribution": "per provider terms",
        "privacy": "Aggregated rates/availability only — rising price + falling availability = demand shock proxy.",
        "supports": ["occupancy_proxy", "demand_signal"],
    },
    "ticket_resale": {
        "name": "Ticket resale curves (TicketsData / SeatGeek Platform)", "category": "events",
        "trust": PLATFORM_SOURCE, "free": "trial / free platform tiers", "key_required": True,
        # Public listing prices + volume as demand-intensity signal — never buyer/seller identity.
        "allowed_use": ["demand_signal", "price_curve"],
        "prohibited_use": ["buyer_identity", "seller_identity", "individual_tracking"],
        "storable": "derived_only", "freshness": "hourly near kickoff",
        "attribution": "per provider terms",
        "privacy": "Public listing data only; resale spike 48h out = hardcore-fan demand proxy.",
        "supports": ["demand_signal", "price_curve"],
    },
    "odds_historical": {
        "name": "Historical odds / fixtures (OddsPapi / SportMonks / API-Football)", "category": "events",
        "trust": PLATFORM_SOURCE, "free": "free historical exports (JSON/CSV)", "key_required": True,
        "allowed_use": ["demand_signal", "backtest_fixture"],
        "prohibited_use": ["bettor_identity"], "storable": "yes",
        "freshness": "historical", "attribution": "per provider terms",
        "privacy": "Aggregate line movements as interest proxy — inherently anonymous.",
        "supports": ["demand_signal", "backtest_fixture"],
    },
    "pems_traffic": {
        "name": "Caltrans PeMS (freeway loop detectors, US-101/I-280)", "category": "public",
        "trust": OFFICIAL_SOURCE, "free": "free (registration)", "key_required": True,
        "allowed_use": ["traffic_history", "backtest_observation"],
        "prohibited_use": [], "storable": "yes",
        "freshness": "historical aggregates (speed/flow)", "attribution": "Caltrans PeMS",
        "privacy": "Loop-detector flow data — fully aggregate, no vehicles identified.",
        "supports": ["traffic_history", "backtest_observation"],
    },
    "placer_ai": {
        "name": "Placer.ai (pre-aggregated foot-traffic indices)", "category": "mobility",
        "trust": PLATFORM_SOURCE, "free": "free industry reports + limited POI lookup",
        "key_required": True, "allowed_use": ["trend_index", "aggregate_visits"],
        "prohibited_use": ["origin_inference", "individual_tracking", "device_paths"],
        "storable": "derived_only", "freshness": "pre-aggregated indices (debiased)",
        "attribution": "Placer.ai",
        "privacy": "Already aggregated/debiased — no individual origins or device paths. "
                   "Privacy-safer alternative to raw SafeGraph patterns.",
        "supports": ["trend_index", "aggregate_visits"],
    },
    "reddit_scrape_tools": {
        "name": "Reddit scrapers (Apify / Bright Data / Pushshift)", "category": "blocked",
        "trust": PROHIBITED_OR_UNUSABLE, "free": "n/a", "key_required": False,
        "allowed_use": [], "prohibited_use": ["everything"], "storable": "no",
        "freshness": "n/a", "attribution": "n/a",
        "privacy": "Bypasses Reddit's API terms — never use; the official Reddit Data API "
                   "(reddit_public_post), candidate-only, is the sole allowed path.",
        "supports": [],
    },
    "foursquare_os": {
        "name": "Foursquare OS Places (Apache-2.0 dataset)", "category": "public", "trust": PLATFORM_SOURCE,
        "free": "free (Apache-2.0)", "key_required": True, "allowed_use": ["category", "location", "geocode"],
        "prohibited_use": [], "storable": "yes", "freshness": "~monthly snapshots",
        "attribution": "Apache-2.0 notice", "privacy": "no reviews/ratings in dataset",
        "supports": ["category", "location"],
    },
    "ntto": {
        "name": "NTTO / trade.gov tourism data", "category": "public", "trust": OFFICIAL_SOURCE,
        "free": "free (downloads, no API)", "key_required": False,
        "allowed_use": ["source_market", "demand_signal"], "prohibited_use": [],
        "storable": "yes", "freshness": "monthly/annual (lagged)", "attribution": "US public domain",
        "privacy": "aggregate only", "supports": ["source_market"],
    },
    "seed": {
        "name": "Curated seed data (our verified records)", "category": "internal", "trust": VERIFIED_SOURCE,
        "free": "n/a", "key_required": False,
        "allowed_use": ["rating", "hours", "category", "location", "historic", "local_favorite",
                        "verified_fact", "menu"],
        "prohibited_use": [], "storable": "yes", "freshness": "as-curated (re-verify periodically)",
        "attribution": "internal", "privacy": "no PII", "supports": ["historic", "local_favorite", "category"],
    },
    "business_website": {
        "name": "Business's own website / menu", "category": "business", "trust": BUSINESS_OWNED_SOURCE,
        "free": "free (read)", "key_required": False,
        "allowed_use": ["menu", "hours", "open_now", "soccer_pub", "watch_party_event"],
        "prohibited_use": ["mass_scrape"], "storable": "short_ttl", "freshness": "varies — confirm recency",
        "attribution": "link to business", "privacy": "none",
        "supports": ["menu", "hours", "soccer_pub"],
    },
    # --- review platforms (restricted) ---
    "yelp_fusion": {
        "name": "Yelp Fusion API", "category": "review", "trust": PLATFORM_SOURCE,
        "free": "trial only (5k/30d), then paid $229+/mo", "key_required": True,
        "allowed_use": ["rating", "hours", "category"], "prohibited_use": ["store_content", "blend_ratings"],
        "storable": "short_ttl",  # 24h cache max; review excerpts only; logo+link required
        "freshness": "live (24h cache cap)", "attribution": "Yelp logo + links required",
        "privacy": "Cannot store reviews; excerpts only.", "supports": ["rating", "hours", "category"],
    },
    "woosmap": {
        "name": "Woosmap Opening Hours API", "category": "review", "trust": PLATFORM_SOURCE,
        "free": "freemium (request quota), then paid", "key_required": True,
        "allowed_use": ["hours", "open_now", "category", "location"],
        "prohibited_use": ["store_content"], "storable": "short_ttl",
        "freshness": "live (timezone-aware open_now: current/next slice)", "attribution": "Woosmap",
        "privacy": "store-locator hours; confirm licensing for retention.",
        "supports": ["hours", "open_now"],
    },
    "square": {
        "name": "Square Locations API (owner POS)", "category": "business", "trust": BUSINESS_OWNED_SOURCE,
        "free": "free with a Square account (owner access token)", "key_required": True,
        "allowed_use": ["hours", "open_now", "menu", "owner_metrics", "verified_fact"],
        "prohibited_use": ["competitor_data", "store_content"], "storable": "derived_only",
        "freshness": "owner-managed (read/write the owner's own locations)",
        "attribution": "Square", "privacy": "Only locations the owner authorizes.",
        "supports": ["hours", "open_now", "menu"],
    },
    "foursquare_api": {
        "name": "Foursquare Places API (hosted)", "category": "review", "trust": PLATFORM_SOURCE,
        "free": "10k Pro calls/mo free; tips/photos paid", "key_required": True,
        "allowed_use": ["rating", "category", "location", "popularity"], "prohibited_use": ["store_content"],
        "storable": "short_ttl", "freshness": "live", "attribution": "Foursquare",
        "privacy": "per ToS; popularity is a candidate trend signal, never asserted as fact",
        "supports": ["category", "rating", "popularity"],
    },
    "tripadvisor": {
        "name": "TripAdvisor Content API", "category": "review", "trust": PLATFORM_SOURCE,
        "free": "PAYG, approval required (mid-migration)", "key_required": True,
        "allowed_use": ["rating", "cite_link"], "prohibited_use": ["store_content", "cache_reviews"],
        "storable": "id_only",  # only Location ID cacheable; everything else live, mandated display
        "freshness": "live only", "attribution": "bubbles + logo + quote labeling (strict)",
        "privacy": "No storing review/rating content.", "supports": ["rating"],
    },
    "editorial_listicle": {
        "name": "Editorial lists (Eater / The Infatuation / Michelin / local news)",
        "category": "review", "trust": PLATFORM_SOURCE, "free": "no API", "key_required": False,
        "allowed_use": ["cite_link"], "prohibited_use": ["store_content", "copy_text", "verified_fact"],
        "storable": "no", "freshness": "editorial", "attribution": "name + outbound link only",
        "privacy": "Copyrighted prose — cite the fact + link, never copy.",
        "supports": ["cite_link"],
    },
    "opentable": {
        "name": "OpenTable (affiliate/deep-link)", "category": "review", "trust": PLATFORM_SOURCE,
        "free": "partner approval", "key_required": True, "allowed_use": ["reservation_link"],
        "prohibited_use": ["api_booking"], "storable": "no", "freshness": "live",
        "attribution": "per partner terms", "privacy": "deep-link only", "supports": ["reservation_link"],
    },
    # --- social / public posts ---
    "reddit_public_post": {
        "name": "Reddit Data API (official, approved)", "category": "social", "trust": PUBLIC_POST_CANDIDATE,
        "free": "100 QPM free non-commercial; OAuth + pre-approval", "key_required": True,
        "allowed_use": ["candidate_signal", "sentiment"],
        "prohibited_use": ["verified_fact", "store_usernames", "store_deleted_content", "train_models"],
        "storable": "derived_only",  # aggregate signals only; honor deletions; no usernames
        "freshness": "live", "attribution": "Reddit (per Data API terms)",
        "privacy": "No usernames; delete content removed on Reddit; never treat as fact.",
        "supports": ["candidate_signal", "sentiment"],
    },
    # --- explicitly blocked ---
    "unauthorized_scrape": {
        "name": "Unauthorized scraping / reverse-engineered endpoints (e.g. Resy, gated sites)",
        "category": "blocked", "trust": PROHIBITED_OR_UNUSABLE, "free": "n/a", "key_required": False,
        "allowed_use": [], "prohibited_use": ["everything"], "storable": "no",
        "freshness": "n/a", "attribution": "n/a", "privacy": "Violates ToS — never use.",
        "supports": [],
    },
}

# ── claim rules: which sources can SUPPORT a claim without extra verification ───
# always_verify=True -> the claim ALWAYS needs verification regardless of source.
CLAIM_RULES: dict[str, dict] = {
    "rating": {"sufficient": {"places_api", "yelp_fusion", "foursquare_api", "tripadvisor", "gbp", "seed"}, "always_verify": False},
    "hours": {"sufficient": {"places_api", "gbp", "business_website", "seed", "yelp_fusion", "woosmap", "square"}, "always_verify": False},
    "open_now": {"sufficient": {"places_api", "gbp", "business_website", "yelp_fusion", "woosmap", "square"}, "always_verify": False},
    "category": {"sufficient": {"places_api", "foursquare_os", "foursquare_api", "osm_overpass", "gbp", "business_website", "seed"}, "always_verify": False},
    "menu": {"sufficient": {"business_website", "gbp"}, "always_verify": False},
    "allergy_safe": {"sufficient": set(), "always_verify": True},   # never "guaranteed safe"
    "allergen": {"sufficient": set(), "always_verify": True},
    "soccer_pub": {"sufficient": {"official_event", "business_website"}, "always_verify": False},
    "watch_party_event": {"sufficient": {"official_event", "business_website"}, "always_verify": False},
    "historic": {"sufficient": {"seed"}, "always_verify": False},
    "local_favorite": {"sufficient": {"seed"}, "always_verify": False},
    "hidden_gem": {"sufficient": {"places_api", "yelp_fusion", "foursquare_api", "seed"}, "always_verify": False},
    "travel_time": {"sufficient": {"routes_api", "mapbox_matrix", "openrouteservice"}, "always_verify": False},
    "traffic": {"sufficient": {"routes_api", "mapbox_matrix"}, "always_verify": False},   # LIVE traffic only
    "place_density": {"sufficient": {"places_insights", "osm_overpass", "foursquare_api"}, "always_verify": False},
    "popularity": {"sufficient": set(), "always_verify": True},   # trendiness = candidate signal, never fact
    "tourist_zone": {"sufficient": set(), "always_verify": True},  # an aggregate proxy inference, not a fact
    "foot_traffic": {"sufficient": {"safegraph"}, "always_verify": False},  # k-anon aggregate ONLY (no origin)
    "closure_status": {"sufficient": {"places_api", "gbp", "official_event", "city_open_data"}, "always_verify": False},
    "open_claim_realtime": {"sufficient": {"gbp", "business_website"}, "always_verify": False},
}


def is_source_allowed(source_type: str, use_case: str) -> bool:
    s = SOURCE_CATALOG.get(source_type)
    if not s or s["trust"] == PROHIBITED_OR_UNUSABLE:
        return False
    return use_case in s.get("allowed_use", [])


def get_allowed_sources(use_case: str) -> list[str]:
    return sorted(sid for sid in SOURCE_CATALOG if is_source_allowed(sid, use_case))


def label_evidence(source_type: str, freshness: str = "unknown", confidence: float = 0.6) -> dict:
    """Map a source + freshness + raw confidence to a UI evidence label + adjusted confidence."""
    s = SOURCE_CATALOG.get(source_type)
    if not s:
        return {"label": NEEDS_VERIFICATION, "confidence": round(min(confidence, 0.4), 2),
                "ui_label": UI_LABEL[NEEDS_VERIFICATION], "storable": "no", "source_known": False}
    label = s["trust"]
    conf = min(float(confidence), TRUST_SCORE.get(label, 0.5))
    if label == PROHIBITED_OR_UNUSABLE:
        return {"label": PROHIBITED_OR_UNUSABLE, "confidence": 0.0,
                "ui_label": UI_LABEL[PROHIBITED_OR_UNUSABLE], "storable": "no", "source_known": True}
    if freshness == "stale":
        label = STALE_SOURCE
        conf = round(conf * 0.6, 2)
    return {"label": label, "confidence": round(conf, 2), "ui_label": UI_LABEL[label],
            "storable": s.get("storable", "no"), "attribution": s.get("attribution"),
            "source_known": True}


def requires_verification(source_type: str, claim_type: str) -> bool:
    """True if a claim of claim_type from source_type still needs verification before we assert it."""
    if source_type not in SOURCE_CATALOG:
        return True
    if SOURCE_CATALOG[source_type]["trust"] == PROHIBITED_OR_UNUSABLE:
        return True
    rule = CLAIM_RULES.get(claim_type)
    if rule is None:
        return True  # unknown claim -> be safe
    if rule["always_verify"]:
        return True
    return source_type not in rule["sufficient"]


def can_store(source_type: str) -> str:
    """Caching/storage policy for a source: yes | id_only | short_ttl | derived_only | no."""
    s = SOURCE_CATALOG.get(source_type)
    return s.get("storable", "no") if s else "no"


# ── integration status (live / seeded / mocked / blocked_by_credentials / prohibited) ──
import os  # noqa: E402

# baseline capability status per source (no creds present)
_STATUS = {
    "nws_weather": "live", "osm_overpass": "live", "city_open_data": "live",
    "foursquare_os": "blocked_by_credentials", "seed": "seeded", "ntto": "seeded",
    "official_event": "seeded", "business_website": "seeded",
    "places_api": "blocked_by_credentials", "gbp": "blocked_by_credentials",
    "ga4": "blocked_by_credentials", "routes_api": "blocked_by_credentials",
    "mapbox_matrix": "blocked_by_credentials", "openrouteservice": "blocked_by_credentials",
    "places_insights": "blocked_by_credentials", "safegraph": "blocked_by_credentials",
    "placer_ai": "blocked_by_credentials", "reddit_scrape_tools": "prohibited",
    "flight_arrivals": "blocked_by_credentials", "hotel_rates": "blocked_by_credentials",
    "ticket_resale": "blocked_by_credentials", "odds_historical": "blocked_by_credentials",
    "pems_traffic": "blocked_by_credentials",
    "translation_api": "blocked_by_credentials", "transit_511": "blocked_by_credentials",
    "reddit_public_post": "blocked_by_credentials", "yelp_fusion": "blocked_by_credentials",
    "woosmap": "blocked_by_credentials", "square": "blocked_by_credentials",
    "foursquare_api": "blocked_by_credentials", "tripadvisor": "blocked_by_credentials",
    "opentable": "blocked_by_credentials", "editorial_listicle": "seeded",
    "trends_official": "blocked_by_credentials", "trends_pytrends": "prohibited",
    "unauthorized_scrape": "prohibited",
}
for _sid, _s in SOURCE_CATALOG.items():
    _s["status"] = _STATUS.get(_sid, "seeded")

# env var that unlocks each keyed source; OAUTH sources need owner authorization
ENV_KEY = {
    "places_api": "GOOGLE_MAPS_API_KEY", "routes_api": "GOOGLE_MAPS_API_KEY",
    "translation_api": "GOOGLE_MAPS_API_KEY", "transit_511": "API_511_TOKEN",
    "ga4": "GA4_PROPERTY_ID", "gbp": "GBP_OAUTH_TOKEN",
    "trends_official": "GOOGLE_TRENDS_TOKEN", "yelp_fusion": "YELP_API_KEY",
    "foursquare_api": "FOURSQUARE_API_KEY", "foursquare_os": "FOURSQUARE_API_KEY",
    "tripadvisor": "TRIPADVISOR_API_KEY", "woosmap": "WOOSMAP_API_KEY",
    "square": "SQUARE_ACCESS_TOKEN", "mapbox_matrix": "MAPBOX_TOKEN",
    "openrouteservice": "ORS_API_KEY", "places_insights": "GOOGLE_MAPS_API_KEY",
    "safegraph": "SAFEGRAPH_API_KEY", "placer_ai": "PLACER_API_KEY",
    "flight_arrivals": "FLIGHT_API_KEY", "hotel_rates": "HOTEL_RATES_API_KEY",
    "ticket_resale": "TICKETS_API_KEY", "odds_historical": "ODDS_API_KEY",
    "pems_traffic": "PEMS_API_KEY",
}
_NO_KEY_LIVE = {"nws_weather", "osm_overpass", "city_open_data"}
_OAUTH = {"gbp", "ga4", "reddit_public_post", "opentable"}


def integration_status(source_id: str) -> str:
    """Runtime status: available | missing_key | blocked_by_oauth | using_seed_fallback | prohibited."""
    s = SOURCE_CATALOG.get(source_id)
    if not s:
        return "unknown"
    if s["trust"] == PROHIBITED_OR_UNUSABLE or s["status"] == "prohibited":
        return "prohibited"
    if source_id in _NO_KEY_LIVE or s["status"] in ("live", "seeded"):
        return "available" if s["status"] == "live" else "using_seed_fallback"
    key = ENV_KEY.get(source_id)
    if key and os.getenv(key):
        return "available"
    if source_id in _OAUTH:
        return "blocked_by_oauth"
    if key:
        return "missing_key"
    return "using_seed_fallback"
