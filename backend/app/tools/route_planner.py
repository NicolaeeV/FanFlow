"""Traffic-aware route tradeoffs.

For each recommendation we estimate how the place sits on a match-day route: ETA, the extra
minutes traffic likely adds, how risky the trip is, whether the fan still makes kickoff, and
how bad the post-match exit will be — then label the tradeoff so a fan can choose
"better place but slower" vs "slightly different local place but faster/easier" vs
"backup if traffic or crowds get bad".

Sources, honestly labeled:
  - a live Google Routes call (only if GOOGLE_MAPS_API_KEY is set AND the call succeeds) -> 'live'
  - live 511 transit alerts feed transit risk (via transit_connector)
  - otherwise everything is 'estimated' from seeded Bay Area baselines + match-stage heuristics
    (NEVER presented as live)
  - no coordinates / no route -> 'needs_verification'
"""
from __future__ import annotations
from ._geo import haversine_km
from .transit_connector import get_route, ROUTE_SEED
from .fan_journey import POST_CELEBRATION, LATE_NIGHT, WATCH_PARTY, SOCCER_FANS
from . import neighborhoods as _nb

# free-flow driving minutes from a neighborhood to Levi's Stadium — sourced from the single
# neighborhood/vicinity model so there's one place to keep Bay Area facts accurate.
DRIVE_BASE_MIN = {nb_id: meta["drive_base_min"] for nb_id, meta in _nb.NEIGHBORHOODS.items()}
POST_STAGES = {POST_CELEBRATION, LATE_NIGHT, WATCH_PARTY, SOCCER_FANS}
TRADEOFF_LABELS = {"best_fit_but_traffic", "faster_outside_traffic", "easiest_transit",
                   "closest_to_stadium", "local_detour_worth_it", "avoid_after_match",
                   "backup_if_gridlock"}
ROUTE_MODES = {"driving", "vta", "caltrain", "ace", "walking", "rideshare", "unknown"}
_RISK_RANK = {"low": 0, "medium": 1, "high": 2, "unknown": 1}
_TRANSIT_MODES = {"vta", "caltrain", "ace", "transit"}

_LABEL_NOTES = {
    "best_fit_but_traffic": "Strongest pick, but match-day traffic adds ~{delay} min by car right now — leave early or take transit.",
    "closest_to_stadium": "Closest to the stadium (~{eta} min) — easy to reach, though the post-match exit gets congested.",
    "easiest_transit": "Easiest by VTA/Caltrain (~{eta} min) — skips the match-day road gridlock.",
    "avoid_after_match": "Great before the match, but driving out right after is gridlocked (~{delay} min extra) — walk it off or take transit.",
    "faster_outside_traffic": "A bit farther out, but outside the stadium traffic pocket — faster and easier to reach and leave (~{eta} min).",
    "local_detour_worth_it": "A short detour off the main route — worth it if you have the time.",
    "backup_if_gridlock": "Keep as a backup if traffic or crowds get bad — easier to reach and leave.",
}


def _mode_of(travel_mode) -> str:
    m = (travel_mode or "").lower()
    if m in _TRANSIT_MODES:
        return m
    if m in ("driving", "rideshare", "walking"):
        return m
    return "unknown"


def _display_mode(mode: str) -> str:
    if mode == "transit":
        return "vta"
    return mode if mode in ROUTE_MODES else "unknown"


def _dist_to_stadium(place: dict, event: dict):
    vlat = (event or {}).get("venue_lat", 37.4033)
    vlon = (event or {}).get("venue_lon", -121.9694)
    if place.get("lat") is None or place.get("lon") is None:
        return None
    return round(haversine_km(place["lat"], place["lon"], vlat, vlon), 1)


def _drive_base(place: dict, dist):
    """(minutes, seeded?) free-flow driving estimate to the stadium."""
    nb = place.get("neighborhood_id", "")
    if nb in DRIVE_BASE_MIN:
        return DRIVE_BASE_MIN[nb], True
    if dist is None:
        return None, False
    return max(5, round(dist / 0.55)), False  # ~33 km/h surface streets


def _band(dist):
    if dist is None:
        return "unknown"
    if dist <= 3.5:
        return "near"
    if dist <= 9:
        return "mid"
    return "far"


def _traffic(mode: str, band: str, is_post: bool, route: dict):
    """Return (traffic_delay_min, route_risk, post_match_exit_risk)."""
    if band == "unknown" or mode == "unknown":
        return 0, "unknown", "unknown"
    if mode in ("driving", "rideshare"):
        delay = {"near": 38 if is_post else 20,
                 "mid": 20 if is_post else 12,
                 "far": 14 if is_post else 8}[band]
        risk = "high" if delay >= 25 else "medium" if delay >= 12 else "low"
        if mode == "rideshare" and is_post:           # surge + pickup gridlock
            risk = "high" if risk != "low" else "medium"
        exit_risk = {"near": "high", "mid": "medium", "far": "low"}[band]
        return delay, risk, exit_risk
    if mode in _TRANSIT_MODES:
        rr = route.get("route_risk") if route.get("available") else "low"
        rr = rr if rr in ("low", "medium", "high") else "low"
        delay = {"high": 8, "medium": 4, "low": 0}[rr]
        exit_risk = "medium" if band == "near" else "low"   # crowded platforms near stadium
        return delay, rr, exit_risk
    if mode == "walking":
        return 0, ("medium" if band == "far" else "low"), "low"
    return 0, "unknown", "unknown"


DWELL_MIN = 40  # rough time spent at the place before heading to the stadium


def _arrival_buffer(eta, is_post: bool, minutes_before_kickoff=None, mode="unknown"):
    """Will the fan still make kickoff? When the lead time is stated, compute a real margin
    (lead time − travel − time spent eating); otherwise fall back to an ETA-based hint.

    Returns None when the travel mode is unknown — without knowing how the fan is getting
    around we won't assert a 'comfortable/tight' arrival they never gave us the basis for."""
    if is_post or eta is None or mode == "unknown":
        return None
    if minutes_before_kickoff is not None:
        margin = minutes_before_kickoff - eta - DWELL_MIN
        if margin >= 30:
            return "comfortable"
        if margin >= 10:
            return "tight — leave promptly"
        if margin >= 0:
            return "very tight — you may miss kickoff"
        return "won't make kickoff — better to eat after the match"
    if eta <= 20:
        return "comfortable"
    if eta <= 40:
        return "tight — leave early"
    return "risky — allow extra time"


def _intrinsic_label(mode: str, band: str, is_post: bool, route_risk: str, exit_risk: str):
    if is_post and mode in ("driving", "rideshare") and exit_risk == "high":
        return "avoid_after_match"
    if band == "near":
        return "closest_to_stadium"
    if mode in _TRANSIT_MODES:
        return "easiest_transit"
    if mode in ("driving", "rideshare") and route_risk in ("medium", "high"):
        return "best_fit_but_traffic"
    return None


def _fill_note(label, eta, delay):
    if label and label in _LABEL_NOTES:
        return _LABEL_NOTES[label].format(eta=eta if eta is not None else "?",
                                          delay=delay)
    if eta is None:
        return "Route not on file — confirm directions and timing before you go."
    return f"About {eta} min each way; plan for match-day delays."


def _live_route(place: dict, event: dict, mode: str):
    """A genuine live travel-time call via the routing provider chain (Google Routes / Mapbox /
    OpenRouteService) — only with a key, never faked. None on any failure so we fall back to
    clearly-labeled estimates. Returns {eta_minutes, traffic_aware, source}."""
    if place.get("lat") is None or place.get("lon") is None:
        return None
    from .routing_providers import live_eta
    origin = (place["lat"], place["lon"])
    dest = ((event or {}).get("venue_lat", 37.4033), (event or {}).get("venue_lon", -121.9694))
    return live_eta(origin, dest, mode)


def assess_route(place: dict, event: dict | None = None, requested_time: dict | None = None,
                 stage: str | None = None, travel_mode: str | None = None,
                 minutes_before_kickoff: int | None = None) -> dict:
    """Traffic-aware route assessment for one place, for the fan's match stage + mode."""
    mode = _mode_of(travel_mode)
    dist = _dist_to_stadium(place, event or {})
    band = _band(dist)
    is_post = stage in POST_STAGES

    drive_base, seeded = _drive_base(place, dist)
    transit_seed = ROUTE_SEED.get(place.get("neighborhood_id", ""))
    if mode in ("driving", "rideshare", "unknown"):
        base = drive_base
    elif mode in _TRANSIT_MODES:
        base = transit_seed["est_minutes"] if transit_seed else (round(drive_base * 1.8) if drive_base else None)
    elif mode == "walking":
        base = round(dist * 12) if dist is not None else None
    else:
        base = drive_base

    route = get_route(place, event or {}, requested_time)
    delay, route_risk, exit_risk = _traffic(mode, band, is_post, route)

    # a live provider overrides the estimate when available
    live = _live_route(place, event or {}, mode)
    source = "estimated"
    if live and base is not None and live.get("traffic_aware"):
        # traffic-aware provider (Google Routes / Mapbox) → genuine live travel time
        eta = live["eta_minutes"]
        delay = max(0, eta - base)
        route_risk = "high" if delay >= 25 else "medium" if delay >= 12 else "low"
        source = "live"
    elif live and base is not None:
        # routed duration with NO live traffic (OpenRouteService): sharpen the base ETA, but
        # the congestion delay stays our modeled estimate — never sold as live traffic
        eta = max(live["eta_minutes"], base) + delay
        source = "estimated"
    elif mode in _TRANSIT_MODES and route.get("freshness") == "live":
        eta = (base + delay) if base is not None else None
        source = "live"
    elif base is None:
        eta, source = None, "needs_verification"
    else:
        eta = base + delay

    label = _intrinsic_label(mode, band, is_post, route_risk, exit_risk)
    note = _fill_note(label, eta, delay)
    return {
        "eta_minutes": eta,
        "route_mode": _display_mode(mode),
        "traffic_delay_estimate": delay,
        "route_risk": route_risk,
        "arrival_buffer_before_kickoff": _arrival_buffer(eta, is_post, minutes_before_kickoff, mode),
        "post_match_exit_risk": exit_risk,
        "route_tradeoff_label": label,
        "route_tradeoff_note": note,
        "source": source,
        "route_dist_km": dist,
    }


def refine_slot_tradeoff(slot: str, card: dict, primary: dict | None, stage: str | None,
                         time_available_min: int | None = None) -> tuple:
    """Slot-aware label, using cross-card comparison the per-card pass can't see.

    Returns (label, note). Operates on the flat route fields already on the cards."""
    is_post = stage in POST_STAGES
    label = card.get("route_tradeoff_label")
    eta = card.get("eta_minutes")
    delay = card.get("traffic_delay_estimate", 0)
    mode = (card.get("route_mode") or "").lower()

    def transit(c):
        return (c.get("route_mode") or "").lower() in _TRANSIT_MODES

    if slot == "local_alternative" and primary:
        faster = (delay < primary.get("traffic_delay_estimate", 99)
                  and _RISK_RANK.get(card.get("route_risk"), 1) <= _RISK_RANK.get(primary.get("route_risk"), 1)
                  and (card.get("route_dist_km") or 0) >= (primary.get("route_dist_km") or 0) - 0.1)
        if faster:
            label = "faster_outside_traffic"
        elif transit(card):
            label = "easiest_transit"
    elif slot == "backup":
        if is_post or (primary and primary.get("post_match_exit_risk") == "high"):
            label = "backup_if_gridlock"
        elif transit(card):
            label = "easiest_transit"
    elif slot == "worth_trying":
        if not time_available_min or time_available_min >= 150:
            label = "local_detour_worth_it"

    note = _fill_note(label, eta, delay) if label else card.get("route_tradeoff_note")
    return label, note
