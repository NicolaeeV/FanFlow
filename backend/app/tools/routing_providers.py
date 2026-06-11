"""Live travel-time / traffic provider chain (origin: San José / Bay Area → Levi's Stadium).

No single free API is perfect, so we register the real ones and use whichever has a key:
  - Google Routes (TRAFFIC_AWARE)  — live traffic
  - Mapbox Matrix                  — live traffic (generous free tier)
  - OpenRouteService               — routed duration, NO live traffic (historical speeds)

Each fetcher needs a key and returns {eta_minutes, traffic_aware, source} from a genuine call,
or None. OFFLINE / NO KEY → None → the caller uses its clearly-labeled ESTIMATED model. We only
label a route "live" when a TRAFFIC-AWARE provider actually answered — an OpenRouteService
duration sharpens the base ETA but never gets sold as live traffic. Nothing here fabricates.
"""
from __future__ import annotations
import os
from .source_catalog import integration_status

# priority: live-traffic providers first, then the no-traffic routed estimate
PROVIDERS = [
    {"id": "routes_api", "label": "Google Routes (traffic-aware)", "traffic": True},
    {"id": "mapbox_matrix", "label": "Mapbox Matrix (traffic-aware)", "traffic": True},
    {"id": "openrouteservice", "label": "OpenRouteService (no live traffic)", "traffic": False},
]


def provider_status() -> dict:
    return {p["id"]: integration_status(p["id"]) for p in PROVIDERS}


def _fetch_google(o, d, mode):
    key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not key:
        return None
    try:
        import httpx
        body = {
            "origin": {"location": {"latLng": {"latitude": o[0], "longitude": o[1]}}},
            "destination": {"location": {"latLng": {"latitude": d[0], "longitude": d[1]}}},
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE",
        }
        r = httpx.post("https://routes.googleapis.com/directions/v2:computeRoutes", json=body, timeout=8,
                       headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": "routes.duration"})
        r.raise_for_status()
        dur = r.json()["routes"][0]["duration"]
        return {"eta_minutes": round(int(str(dur).rstrip("s")) / 60), "traffic_aware": True,
                "source": "routes_api"}
    except Exception:
        return None


def _fetch_mapbox(o, d, mode):
    key = os.getenv("MAPBOX_TOKEN", "")
    if not key:
        return None
    try:
        import httpx
        prof = "driving-traffic"
        url = f"https://api.mapbox.com/directions-matrix/v1/mapbox/{prof}/{o[1]},{o[0]};{d[1]},{d[0]}"
        r = httpx.get(url, params={"access_token": key, "annotations": "duration"}, timeout=8)
        r.raise_for_status()
        secs = r.json()["durations"][0][1]
        return {"eta_minutes": round(secs / 60), "traffic_aware": True, "source": "mapbox_matrix"}
    except Exception:
        return None


def _fetch_ors(o, d, mode):
    key = os.getenv("ORS_API_KEY", "")
    if not key:
        return None
    try:
        import httpx
        r = httpx.post("https://api.openrouteservice.org/v2/matrix/driving-car",
                       headers={"Authorization": key},
                       json={"locations": [[o[1], o[0]], [d[1], d[0]]], "metrics": ["duration"]}, timeout=8)
        r.raise_for_status()
        secs = r.json()["durations"][0][1]
        return {"eta_minutes": round(secs / 60), "traffic_aware": False, "source": "openrouteservice"}
    except Exception:
        return None


_FETCHERS = {"routes_api": _fetch_google, "mapbox_matrix": _fetch_mapbox,
             "openrouteservice": _fetch_ors}


def live_eta(origin, dest, mode: str = "driving") -> dict | None:
    """First available provider wins. Returns {eta_minutes, traffic_aware, source} or None.
    Live-traffic providers (traffic_aware=True) are tried before the no-traffic estimate."""
    if mode not in ("driving", "rideshare"):
        return None            # transit handled by 511; walking is distance-based
    if not origin or not dest or None in origin or None in dest:
        return None
    for p in PROVIDERS:
        if integration_status(p["id"]) != "available":
            continue
        res = (_FETCHERS.get(p["id"]) or (lambda *_: None))(origin, dest, mode)
        if res:
            return res
    return None
