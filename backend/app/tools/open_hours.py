"""Open-hours truth layer for match-day trip stages.

For a place + match, computes whether it's viable PRE-match, POST-match, and LATE-night —
using only allowed hours sources (Places API fields, business website/official hours, seeded
verified hours). If hours are missing/stale we say `needs_verification`, never "open now".

Anchored to the venue local day (America/Los_Angeles). A typical match ~2h; egress pushes the
post-match wave to roughly kickoff+2 .. kickoff+4.
"""
from __future__ import annotations
from .hours import kickoff_hour, kickoff_weekday, is_open_at, hours_for_day

CONF = {"places_api": 0.85, "business_website": 0.6, "seed": 0.5, None: 0.3}


def _hours_source(place: dict) -> str | None:
    if place.get("google_place_id"):
        return "places_api"
    food = place.get("food", {}) or {}
    if place.get("website") and food.get("info_status") == "menu_published":
        return "business_website"
    if place.get("hours"):
        return "seed"
    return None


def _viable(place: dict, wd: int, hour: int) -> str:
    """yes | no | unknown for a place open at a given weekday/hour."""
    st = is_open_at(place, wd, hour)
    return {"open": "yes", "closed": "no", "unknown": "unknown"}[st]


def assess_open_hours(place: dict, event: dict, requested_time: dict | None = None) -> dict:
    wd = (requested_time or {}).get("weekday", kickoff_weekday(event))
    ko = kickoff_hour(event)
    src = _hours_source(place)
    freshness = "live" if src == "places_api" else (place.get("data_freshness") or "unknown")

    pre = _viable(place, wd, max(0, ko - 1))            # ~1h before kickoff
    during = _viable(place, wd, min(23, ko + 1))         # mid-match
    post = _viable(place, wd, min(23, ko + 2))           # post-match wave start
    post_late = _viable(place, wd, min(23, ko + 3))      # deeper post-match
    # "late night" is relative to kickoff: after a 6pm match the late wave is ~21-22, not 11pm
    late = _viable(place, wd, min(23, max(ko + 3, 21)))

    post_match_viable = "yes" if (post == "yes" or post_late == "yes") else (
        "no" if (post == "no" and post_late == "no") else "unknown")

    # open_now only assertable from a LIVE source; otherwise needs verification
    if requested_time and requested_time.get("has_time"):
        open_now_status = {"yes": "open", "no": "closed", "unknown": "unknown"}[
            _viable(place, wd, requested_time["hour"])]
        if open_now_status in ("open", "closed") and src != "places_api":
            # we know the listed hours, but not live status from a non-live source
            open_now_status = "needs_verification" if open_now_status == "open" else "closed"
    else:
        open_now_status = "needs_verification" if src != "places_api" else "unknown"

    call_ahead = (src in (None, "seed")) or "unknown" in (pre, post_match_viable, late) or freshness == "stale"
    conf = CONF.get(src, 0.3)
    if freshness == "stale":
        conf = round(conf * 0.6, 2)

    return {
        "open_now_status": open_now_status,
        "open_at_match_window": during,
        "pre_match_viable": pre,
        "post_match_viable": post_match_viable,
        "late_night_viable": late,
        "hours_source": src or "none",
        "hours_for_match_day": hours_for_day(place, wd),
        "freshness": freshness,
        "confidence": conf,
        "call_ahead_required": bool(call_ahead),
    }


def viable_for_stage(assessment: dict, stage: str) -> bool:
    """True unless we KNOW the place is closed for that stage ('no'). Unknown stays in (labeled)."""
    if stage in ("post_match_celebration", "late_night_food", "watch_party_no_ticket"):
        return assessment["post_match_viable"] != "no" if stage != "late_night_food" else assessment["late_night_viable"] != "no"
    if stage in ("pre_match_food", "pre_match_drinks", "family_meal", "stadium_arrival"):
        return assessment["pre_match_viable"] != "no"
    return True
