"""Small geo + hours helpers shared by the intelligence modules."""
from __future__ import annotations
import math

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    if None in (lat1, lon1, lat2, lon2):
        return 8.0
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _weekday_from_iso(iso_local: str) -> str:
    """Best-effort weekday key (mon..sun) from an ISO local datetime string."""
    try:
        y, m, d = int(iso_local[0:4]), int(iso_local[5:7]), int(iso_local[8:10])
        # Zeller-free: use ordinal via datetime without tz.
        from datetime import date
        return WEEKDAYS[date(y, m, d).weekday()]
    except Exception:
        return "fri"


def closes_before(business: dict, event: dict, post_match_hour_offset: int = 4) -> tuple[bool, int | None]:
    """Does the business close before the post-match wave ends?
    Returns (closes_early, close_hour)."""
    hours = business.get("hours", {})
    wd = _weekday_from_iso(event.get("kickoff_local", ""))
    day = hours.get(wd) or hours.get("fri") or {}
    close = day.get("close")
    if not close:
        return (False, None)
    try:
        close_h = int(str(close)[:2])
    except Exception:
        return (False, None)
    try:
        kickoff_h = int(event.get("kickoff_local", "T18")[11:13])
    except Exception:
        kickoff_h = 18
    target = kickoff_h + post_match_hour_offset  # when the post-match wave fades
    # close_h of 23 or 00/01 wraps midnight; treat <6 as next-day late close.
    eff_close = close_h + 24 if close_h < 6 else close_h
    return (eff_close < target, close_h)


def open_during_window(business: dict, event: dict) -> float:
    """0..1: fraction of the pre+post match window the business is open."""
    early, close_h = closes_before(business, event)
    return 0.6 if early else 1.0


def latest_close_hour(business: dict) -> int | None:
    """Latest closing hour across known days (handles after-midnight wrap)."""
    best = None
    for day in (business.get("hours", {}) or {}).values():
        c = (day or {}).get("close")
        if not c:
            continue
        try:
            h = int(str(c)[:2])
        except Exception:
            continue
        h = h + 24 if h < 6 else h  # 01:00 -> 25 (late), 23:00 -> 23
        best = h if best is None else max(best, h)
    return best
