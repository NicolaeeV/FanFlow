"""Google Places API (New) connector — live hours/status/rating, with seed fallback.

Talks to Places API (New) Place Details when GOOGLE_MAPS_API_KEY is set; otherwise returns
the seeded record labeled source=seed. Stores only allowed fields (place_id + freshness;
never copies review bodies). NEVER infers allergy safety from Places. If live fields are
missing -> the caller treats them as needs_verification. No Popular Times, ever.
"""
from __future__ import annotations
from ..config import GOOGLE_MAPS_API_KEY, HAS_MAPS

# Allowed field mask (Places API New). Atmosphere fields cost more — keep tight.
FIELD_MASK = [
    "id", "displayName", "formattedAddress", "location", "businessStatus",
    "regularOpeningHours", "currentOpeningHours", "rating", "userRatingCount",
    "priceLevel", "types", "primaryType", "websiteUri", "nationalPhoneNumber",
    "editorialSummary", "goodForChildren", "goodForGroups", "allowsDogs", "restroom",
    "servesBeer", "servesVegetarianFood", "takeout", "delivery", "dineIn", "photos",
    # Up to 5 reviews — we keep ONLY text + rating + relative time (recency), NEVER the author
    # name/photo/URI. Anonymized public review text used as evidence, so we can explain WHY locals
    # love a place and WHY it isn't ranked higher. Same SKU tier as the atmosphere fields above.
    "reviews",
]


def normalize_business_status(s: str | None) -> str:
    """Places statuses -> our model. CLOSED_* (temp or permanent) => not recommendable."""
    if not s:
        return "unknown"
    s = s.upper()
    if s in ("CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"):
        return "closed"
    if s == "OPERATIONAL":
        return "operational"
    return s.lower()


def fetch_place_details(place_id: str) -> dict | None:
    """Live Place Details call. Returns raw Places JSON, or None if no key/error.

    Isolated so tests can monkeypatch it with a mocked Places response.
    """
    if not (HAS_MAPS and place_id):
        return None
    try:
        import httpx
        url = f"https://places.googleapis.com/v1/places/{place_id}"
        headers = {"X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                   "X-Goog-FieldMask": ",".join(FIELD_MASK)}
        r = httpx.get(url, headers=headers, timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _hours_to_seed_shape(opening: dict | None) -> dict | None:
    """Map the official Google Places OpeningHours `periods` -> our {mon..sun: {...}} shape.

    Faithful to the real schema:
      - multiple periods on one day (split lunch/dinner hours) -> an `intervals` list
      - 24-hour places (one `open` at day 0, time 00:00, with NO `close`) -> every day 00:00-24:00
      - overnight close (close.day != open.day, e.g. Fri 18:00 -> Sat 01:00) -> kept on the
        open day; our is_open_at handles the past-midnight wrap
    """
    if not opening or not opening.get("periods"):
        return None
    days = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]  # Places day 0 = Sunday
    # "always open": a single period with an `open` (day 0, 00:00) and no `close`
    periods = opening["periods"]
    if len(periods) == 1 and periods[0].get("open") and not periods[0].get("close"):
        return {d: {"open": "00:00", "close": "24:00"} for d in days}

    by_day: dict[str, list] = {}
    for p in periods:
        o, c = p.get("open"), p.get("close")
        if not o or "day" not in o:
            continue
        d = days[o["day"] % 7]
        oh = f"{o.get('hour', 0):02d}:{o.get('minute', 0):02d}"
        ch = f"{(c or {}).get('hour', 0):02d}:{(c or {}).get('minute', 0):02d}"
        by_day.setdefault(d, []).append({"open": oh, "close": ch})

    out = {}
    for d, ivs in by_day.items():
        if len(ivs) == 1:
            out[d] = ivs[0]                       # single interval -> simple {open, close}
        else:                                     # split hours -> envelope + precise intervals
            ivs.sort(key=lambda i: i["open"])
            out[d] = {"open": ivs[0]["open"], "close": ivs[-1]["close"], "intervals": ivs}
    return out or None


def _special_days(opening: dict | None) -> list:
    """Official `specialDays` (up to the next 7 days that deviate from regular hours, e.g.
    holidays/events) -> ISO date strings. We record WHICH days are special, never inventing
    the special hours themselves."""
    out = []
    for sd in (opening or {}).get("specialDays", []) or []:
        dt = sd.get("date") or {}
        try:
            out.append(f"{dt['year']:04d}-{dt['month']:02d}-{dt['day']:02d}")
        except Exception:
            continue
    return out


def get_place_live(place: dict, force: bool = False, allow_fetch: bool = True) -> dict:
    """Merge live Places fields onto a place when possible; else return it as seed.

    Returns the place with `_source`, `_freshness`, and `_live_fields` set. Never fabricates.

    If the record was already enriched & STORED (has `places_enriched_at`) we serve straight from
    the stored profile and do NOT call Google again — that's the whole point of persisting it
    (one Place Details call at enrich time, then read from Atlas on every request). Pass
    force=True (the enrichment job does) to bypass the store and fetch fresh from Google.

    allow_fetch=False forbids ANY live call (no Place Details, no alt-provider) — used by the
    visitor chat when scoring ~200 candidates, so an un-enriched thin doc doesn't trigger a slow
    live round-trip mid-conversation. It just returns the stored doc as-is.
    """
    if not force and place.get("places_enriched_at"):
        out = dict(place)
        out["_source"] = "places_store"        # stored Google profile (no live call this request)
        out["_freshness"] = "stored"
        out["_live_fields"] = place.get("_enriched_fields", [])
        return out
    if not allow_fetch:
        out = dict(place)
        out.setdefault("_source", "seed")
        out.setdefault("_freshness", out.get("data_freshness", "seed"))
        out["_live_fields"] = []
        return out
    pid = place.get("google_place_id")
    try:
        raw = fetch_place_details(pid) if pid else None
    except Exception:
        raw = None   # any connector failure -> safe seed fallback, never crash
    if not raw:
        out = dict(place)
        # no Google data — try other live hours providers (Yelp / Woosmap / Square) if a key +
        # per-place id exist. Offline / no key → None → clean seed fallback (no fabrication).
        try:
            from .hours_providers import live_hours
            alt = live_hours(place, skip={"places_api"})
        except Exception:
            alt = None
        if alt:
            if alt.get("hours"):
                out["hours"] = alt["hours"]
            if alt.get("special_hours_dates"):
                out["special_hours_dates"] = alt["special_hours_dates"]
            if alt.get("open_now") is not None:
                out["_live_open_now"] = alt["open_now"]
            out["_source"] = alt["source"]
            out["_freshness"] = "live"
            out["_live_fields"] = [k for k in ("hours", "special_hours_dates") if alt.get(k)]
            return out
        out.setdefault("_source", "seed")
        out.setdefault("_freshness", out.get("data_freshness", "seed"))
        out["_live_fields"] = []
        return out

    out = dict(place)
    live = []
    bs = normalize_business_status(raw.get("businessStatus"))
    if bs != "unknown":
        out["business_status"] = bs; live.append("business_status")
    opening = raw.get("currentOpeningHours") or raw.get("regularOpeningHours")
    hours = _hours_to_seed_shape(opening)
    if hours:
        out["hours"] = hours; live.append("hours")
    # official OpeningHours extras: per-place special days (holidays/events) + human-readable text
    special = _special_days(raw.get("currentOpeningHours"))
    if special:
        out["special_hours_dates"] = special; live.append("special_hours_dates")
    if opening and opening.get("weekdayDescriptions"):
        out["hours_text"] = opening["weekdayDescriptions"]
    if raw.get("rating") is not None:
        out["rating"] = raw["rating"]; live.append("rating")
    if raw.get("userRatingCount") is not None:
        out["reviews"] = raw["userRatingCount"]; live.append("reviews")
    if raw.get("websiteUri"):
        out["website"] = raw["websiteUri"]; live.append("website")
    if raw.get("nationalPhoneNumber"):
        out["phone"] = raw["nationalPhoneNumber"]
    if raw.get("primaryType"):
        out["category"] = raw["primaryType"]
    # secondary Google types — the relevance-tag layer uses these so a market that also reads
    # as a deli/cafe keeps that signal (NOT just the single primaryType)
    if raw.get("types"):
        secs = [t for t in raw["types"] if t != raw.get("primaryType")][:6]
        if secs:
            out["secondary_categories"] = secs
    # editorial summary (Google-authored description) + service attributes. These are in the
    # field mask and we pay for them — surface them (snake_case) so tag inference can read
    # "serves sandwiches / takeout / good for groups". Business-facing facts only.
    es = raw.get("editorialSummary")
    if isinstance(es, dict) and es.get("text"):
        out["editorial_summary"] = es["text"]
    elif isinstance(es, str) and es:
        out["editorial_summary"] = es
    for gk, sk in (("goodForChildren", "good_for_children"), ("goodForGroups", "good_for_groups"),
                   ("allowsDogs", "allows_dogs"), ("restroom", "restroom"),
                   ("servesBeer", "serves_beer"), ("servesVegetarianFood", "serves_vegetarian"),
                   ("takeout", "takeout"), ("delivery", "delivery"), ("dineIn", "dine_in")):
        if raw.get(gk) is not None:
            out[sk] = raw[gk]
    # photo readiness — store the COUNT (never the image bytes); feeds the readiness score
    if isinstance(raw.get("photos"), list):
        out["photos"] = len(raw["photos"])
        live.append("photos")
    # reviews — store ONLY anonymized text + rating + relative recency (NO author name/photo/URI).
    # Lets us explain why locals love a place + how fresh its reviews are. PII never stored.
    if isinstance(raw.get("reviews"), list) and raw["reviews"]:
        snippets, rev_ratings, newest_desc = [], [], None
        for rv in raw["reviews"][:5]:
            txt = (rv.get("text") or {})
            body = txt.get("text") if isinstance(txt, dict) else (txt if isinstance(txt, str) else None)
            if body:
                snippets.append(body.strip())
            if rv.get("rating") is not None:
                rev_ratings.append(rv["rating"])
            if newest_desc is None and rv.get("relativePublishTimeDescription"):
                newest_desc = rv["relativePublishTimeDescription"]   # Places returns newest first
        if snippets:
            out["review_snippets"] = snippets
            out["review_sample_ratings"] = rev_ratings
            out["latest_review_age"] = newest_desc      # e.g. "2 weeks ago" / "3 years ago"
            live.append("reviews")
    out["_source"] = "places_api"
    out["_freshness"] = "live"
    out["_live_fields"] = live
    # NOTE: we deliberately do NOT copy review bodies or infer allergy safety here.
    return out
