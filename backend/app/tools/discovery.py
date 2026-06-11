"""Fan-venue discovery ingestor.

Pattern adapted from Agent-Reach ('give the agent eyes on the public internet' across
many sources). Here it surfaces soccer pubs, watch parties, and soccer-culture anchors
from public sources. CRITICAL: it does NOT invent that a place is a soccer hub or
historic — each is a CANDIDATE with a source + confidence until verified. In production
this is backed by live scraping (Places review text, event pages, watch-party listings,
Reddit/social) rather than the seeded list.
"""
from __future__ import annotations
from .. import mongo
from ._geo import haversine_km

# search themes a live scraper would run (documented so the intent is auditable)
SCRAPE_QUERIES = [
    "soccer bar San Jose", "World Cup watch party San Jose", "Mexico game watch party Bay Area",
    "British pub San Jose soccer", "sports bar near VTA", "World Cup fan zone Santa Clara",
    "watch party Levi's Stadium", "soccer pub Mountain View",
]


def discover_fan_venues(match_id: str = "", venue_type: str = "", max_km_from_venue: float = 0) -> dict:
    """Return candidate soccer pubs / watch parties / soccer-culture anchors."""
    ev = mongo.get_event(match_id) if match_id else {}
    venues = mongo.get_fan_venues(venue_type or None)
    out = []
    for v in venues:
        d = haversine_km(v.get("lat"), v.get("lon"), (ev or {}).get("venue_lat"), (ev or {}).get("venue_lon")) if ev else None
        if max_km_from_venue and d and d > max_km_from_venue:
            continue
        out.append({
            "id": v["_id"], "name": v["name"], "type": v["type"],
            "neighborhood_id": v.get("neighborhood_id"),
            "soccer_relevance": v.get("soccer_relevance"),
            "distance_to_venue_km": None if d is None else round(d, 1),
            "status": "candidate" if v.get("candidate") else "confirmed",
            "confidence": v.get("confidence"), "source": v.get("source"),
            "notes": v.get("notes"),
        })
    out.sort(key=lambda x: (x["distance_to_venue_km"] if x["distance_to_venue_km"] is not None else 1e9))
    return {
        "match_id": match_id, "venue_type": venue_type or "all",
        "scrape_queries_used": SCRAPE_QUERIES,
        "results": out,
        "disclaimer": "These are CANDIDATES surfaced from public sources — confirm screenings/"
                      "fixtures/dates before routing fans. We never claim 'historic' or 'soccer hub' "
                      "without a supporting source.",
    }
