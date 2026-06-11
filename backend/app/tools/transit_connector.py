"""Transit connector — 511 SF Bay (GTFS + GTFS-Realtime), with seeded route fallback.

Answers "can the fan reach Levi's from here, and are there alerts?" Live service alerts via
511 when API_511_TOKEN is set (free token); otherwise seeded route notes. GTFS = schedules,
GTFS-Realtime = vehicle updates/service alerts. No scraping.
"""
from __future__ import annotations
import os

API_511_TOKEN = os.getenv("API_511_TOKEN", "")

# seeded route notes per neighborhood -> Levi's Stadium / Great America (illustrative).
ROUTE_SEED = {
    "santa_clara_central": {"nearest_stop": "Great America (VTA Orange Line / ACE / Capitol Corridor)",
                            "mode": "walk/transit", "est_minutes": 15, "line": "VTA Orange / ACE"},
    "downtown_san_jose": {"nearest_stop": "Downtown San José (VTA)",
                          "mode": "transit", "est_minutes": 40, "line": "VTA Orange to Great America"},
    "santana_row": {"nearest_stop": "Santana Row (VTA bus → light rail)",
                    "mode": "transit/drive", "est_minutes": 35, "line": "VTA"},
    "mountain_view_castro": {"nearest_stop": "Mountain View (Caltrain ↔ VTA Orange)",
                             "mode": "transit", "est_minutes": 45, "line": "Caltrain + VTA Orange"},
    "sunnyvale_downtown": {"nearest_stop": "Sunnyvale (Caltrain / VTA)",
                           "mode": "transit", "est_minutes": 40, "line": "Caltrain + VTA"},
    "japantown_san_jose": {"nearest_stop": "Japantown/Ayer (VTA)",
                           "mode": "transit", "est_minutes": 38, "line": "VTA"},
}
LATE_NIGHT_WARN = "VTA/Caltrain service thins out late — check the last train before a post-match plan."


def fetch_service_alerts(operator: str = "RG"):
    """Live 511 GTFS-Realtime service alerts.

    Returns a list on a SUCCESSFUL call (possibly empty = no current alerts), or None when
    there's no token or the call fails — so callers can tell 'live, no alerts' apart from
    'we never reached 511' and never label a failed/seed fetch as live."""
    if not API_511_TOKEN:
        return None
    try:
        import httpx
        r = httpx.get("http://api.511.org/transit/servicealerts",
                      params={"api_key": API_511_TOKEN, "agency": operator, "format": "json"}, timeout=8)
        r.raise_for_status()
        data = r.json()
        return [e.get("alert", {}) for e in data.get("entity", [])][:10]
    except Exception:
        return None


def get_route(place: dict, event: dict, requested_time: dict | None = None) -> dict:
    nb = place.get("neighborhood_id", "")
    seed = ROUTE_SEED.get(nb)
    raw_alerts = fetch_service_alerts()
    live_ok = raw_alerts is not None            # True only when the 511 call actually returned
    alerts = raw_alerts or []
    route_risk = "high" if len(alerts) >= 3 else "medium" if alerts else "low"
    late = bool(requested_time and requested_time.get("label") in ("late night", "after midnight", "midnight"))
    if not seed:
        return {"available": False, "source": "none",
                "route_note": "Route not on file — check VTA/Caltrain or driving directions.",
                "route_risk": "unknown", "alerts": alerts,
                "late_night_warning": LATE_NIGHT_WARN if late else None}
    note = f"{seed['nearest_stop']} → Levi's via {seed['line']} (~{seed['est_minutes']} min, {seed['mode']})"
    return {
        # only claim 511/live when the live call actually succeeded — a failed/keyless fetch
        # is seeded route data and must say so (never label seed as live)
        "available": True, "source": "511" if live_ok else "seed",
        "nearest_stop": seed["nearest_stop"], "mode": seed["mode"],
        "est_minutes": seed["est_minutes"], "line": seed["line"],
        "route_note": note, "route_risk": route_risk, "alerts": alerts,
        "late_night_warning": LATE_NIGHT_WARN if (late or route_risk != "low") else None,
        "freshness": "live" if live_ok else "seed",
    }
