"""Match-day itinerary builder.

Adapted from SmartTourister (nearest-neighbor route sequencing over rated places) and
Smart-Tourist-Guide (ask intent + time available + location, then rank & schedule).
Given a fan's start point, time budget, intent, and the match, it picks a few high-fit
stops (a local-favorite meal + a soccer pub / watch party + the route to the stadium)
and sequences them efficiently with time + travel buffers and a backup option.
"""
from __future__ import annotations
from .. import mongo
from ._geo import haversine_km
from .home_score import home_away_score
from .discovery import discover_fan_venues
from .google_places_connector import get_place_live
from .business_tags import is_food_eligible
from . import neighborhoods as _nb

# neighborhood centroids — sourced from the single neighborhood/vicinity model
NEIGHBORHOOD_COORDS = {nb_id: (meta["lat"], meta["lon"]) for nb_id, meta in _nb.NEIGHBORHOODS.items()}
TRAVEL_MIN_PER_KM = 2.5   # rough mixed transit/drive in match-day traffic


def _coords(start: str):
    return NEIGHBORHOOD_COORDS.get(start, NEIGHBORHOOD_COORDS["downtown_san_jose"])


def _nearest_neighbor(start_lat, start_lon, stops):
    """Greedy nearest-neighbor sequencing (SmartTourister getShortest analogue)."""
    route, cur = [], (start_lat, start_lon)
    rem = stops[:]
    while rem:
        nxt = min(rem, key=lambda s: haversine_km(cur[0], cur[1], s["lat"], s["lon"]))
        leg = haversine_km(cur[0], cur[1], nxt["lat"], nxt["lon"])
        nxt["travel_min_from_prev"] = round(leg * TRAVEL_MIN_PER_KM)
        route.append(nxt)
        rem.remove(nxt)
        cur = (nxt["lat"], nxt["lon"])
    return route


def build_match_day_itinerary(match_id: str, start: str = "downtown_san_jose",
                              time_budget_hours: float = 3.0, intent: str = "pre_match",
                              prefer_langs: list | None = None) -> dict:
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    demand_langs = ({l["lang"] for l in mix.get("language_mix", [])
                     if l["lang"] not in ("en", "other") and l.get("share", 0) >= 0.1}
                    | set(prefer_langs or []))
    slat, slon = _coords(start)

    # 1) candidate food stops ranked by Home-Away-From-Home score. Eligibility is multi-signal
    #    (tags), not primary-category-only — so a neighborhood market/deli that sells prepared
    #    food can be a stop too. Prefer real Google-connected places when any exist.
    # allow_fetch=False: this scans EVERY business (~13k). With live fetch on, each un-enriched
    # doc would trigger a Place Details round-trip → thousands of Google calls → multi-minute stall
    # (a demo-killer if the agent calls this tool). Stored/enriched docs still serve their Google
    # data; thin docs serve as seed. Same discipline the visitor chat uses when scoring candidates.
    all_biz = [get_place_live(b, allow_fetch=False) for b in mongo.get_businesses() if b.get("lat")]
    if any(b.get("google_place_id") for b in all_biz):
        all_biz = [b for b in all_biz if b.get("google_place_id")]
    foods = []
    for b in all_biz:
        if is_food_eligible(b):
            h = home_away_score(b, ev, demand_langs)
            foods.append({"name": b["name"], "type": "food", "lat": b["lat"], "lon": b["lon"],
                          "score": h["home_score"], "why": h["why_recommended"][:2],
                          "suggested_min": 60})
    foods.sort(key=lambda x: x["score"], reverse=True)

    # 2) a soccer pub / watch party (candidate, verified source)
    fans = discover_fan_venues(match_id, "").get("results", [])
    fan_stop = None
    for f in fans:
        if f.get("distance_to_venue_km") is not None and f["distance_to_venue_km"] <= 20 and f.get("neighborhood_id"):
            v = mongo.get_fan_venues()  # need coords
            coord = next((x for x in v if x["_id"] == f["id"]), None)
            if coord:
                fan_stop = {"name": f["name"], "type": f["type"], "lat": coord["lat"], "lon": coord["lon"],
                            "why": [f["notes"] or "fan gathering spot"], "status": f["status"],
                            "source": f["source"], "suggested_min": 75}
                break

    # 3) choose stops to fit the time budget (Smart-Tourist-Guide style)
    stops = []
    if foods:
        stops.append(foods[0])
    if time_budget_hours >= 2.5 and fan_stop:
        stops.append(fan_stop)
    if time_budget_hours >= 4 and len(foods) > 1:
        stops.append(foods[1])

    # stadium as the anchor end (pre-match) — included so the route lands at the venue
    if ev.get("venue_lat"):
        stops_seq = _nearest_neighbor(slat, slon, stops)
        stadium_leg = haversine_km(stops_seq[-1]["lat"] if stops_seq else slat,
                                   stops_seq[-1]["lon"] if stops_seq else slon,
                                   ev["venue_lat"], ev["venue_lon"]) if (stops_seq or True) else 0
        stadium = {"name": ev.get("venue_name", "Levi's Stadium"), "type": "stadium",
                   "lat": ev["venue_lat"], "lon": ev["venue_lon"],
                   "travel_min_from_prev": round(stadium_leg * TRAVEL_MIN_PER_KM),
                   "why": ["kickoff — arrive ~45 min early"], "suggested_min": 0}
        route = stops_seq + [stadium]
    else:
        route = _nearest_neighbor(slat, slon, stops)

    total_min = sum(s.get("travel_min_from_prev", 0) + s.get("suggested_min", 0) for s in route)
    backup = foods[2]["name"] if len(foods) > 2 else (foods[1]["name"] if len(foods) > 1 else None)

    return {
        "match_id": match_id, "start": start, "time_budget_hours": time_budget_hours,
        "intent": intent, "languages": sorted(demand_langs),
        "itinerary": [{"order": i + 1, **{k: v for k, v in s.items() if k not in ("lat", "lon")}}
                      for i, s in enumerate(route)],
        "estimated_total_minutes": total_min,
        "fits_time_budget": total_min <= time_budget_hours * 60 + 15,
        "backup_if_crowded": backup,
        "note": "Sequenced by nearest-neighbor from your start (SmartTourister-style). Fan venues are "
                "candidates from public sources — confirm screenings. Travel times approximate.",
    }
