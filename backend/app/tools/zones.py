"""Bay Area match-route ZONE GRAPH.

The 'zone' is not a circle around Levi's Stadium — it's a movement graph: where fans
are at each trip stage (airport -> hotel -> pre-match -> stadium -> post-match ->
late-night transit -> next-day local experience). Used to route by where a fan
actually is, not just proximity to the venue.

Coordinates are approximate/illustrative; verify against official 2026 maps.
"""
from __future__ import annotations
from ._geo import haversine_km

ZONES = {
    "stadium": [
        {"id": "levis_stadium", "name": "Levi's Stadium", "lat": 37.4033, "lon": -121.9694},
    ],
    "transit": [
        {"id": "great_america_vta", "name": "Great America VTA / ACE / Amtrak", "lat": 37.4090, "lon": -121.9760},
        {"id": "downtown_sj_vta", "name": "Downtown San José VTA hub", "lat": 37.3330, "lon": -121.8900},
        {"id": "mountain_view_caltrain", "name": "Mountain View Caltrain/VTA transfer", "lat": 37.3947, "lon": -122.0758},
        {"id": "sunnyvale_caltrain", "name": "Sunnyvale Caltrain", "lat": 37.3782, "lon": -122.0301},
    ],
    "hotel_cluster": [
        {"id": "santa_clara_hotels", "name": "Santa Clara / North San José hotels", "lat": 37.3880, "lon": -121.9780},
        {"id": "sjc_airport_hotels", "name": "SJC airport hotels", "lat": 37.3639, "lon": -121.9289},
        {"id": "sunnyvale_mtv_hotels", "name": "Sunnyvale / Mountain View business hotels", "lat": 37.3860, "lon": -122.0560},
    ],
    "nightlife": [
        {"id": "san_pedro_square", "name": "San Pedro Square / Downtown San José", "lat": 37.3370, "lon": -121.8950},
        {"id": "santana_row", "name": "Santana Row / Valley Fair", "lat": 37.3210, "lon": -121.9482},
        {"id": "castro_street_mv", "name": "Castro Street, Mountain View", "lat": 37.3940, "lon": -122.0797},
        {"id": "japantown_sj", "name": "Japantown, San José", "lat": 37.3489, "lon": -121.8940},
    ],
    "soccer_culture": [
        {"id": "paypal_park", "name": "PayPal Park (SJ Earthquakes)", "lat": 37.3517, "lon": -121.9250},
    ],
}


def all_zone_points() -> list[dict]:
    out = []
    for ztype, pts in ZONES.items():
        for p in pts:
            out.append({**p, "zone_type": ztype})
    return out


def nearest_zone(lat: float, lon: float, zone_type: str | None = None) -> dict | None:
    pts = ZONES.get(zone_type, []) if zone_type else all_zone_points()
    best, bestd = None, 1e9
    for p in pts:
        d = haversine_km(lat, lon, p["lat"], p["lon"])
        if d < bestd:
            best, bestd = {**p, "distance_km": round(d, 1)}, d
    return best


def get_zone_graph(match_id: str = "") -> dict:
    """Return the full zone graph + the canonical trip-stage flow."""
    return {
        "zones": ZONES,
        "trip_flow": ["airport", "hotel", "pre-match meal", "stadium",
                      "post-match celebration", "late-night transit", "next-day local experience"],
        "note": "Route fans by where they are in the trip, not just distance to the venue. "
                "Coordinates illustrative — verify against official 2026 maps.",
    }
