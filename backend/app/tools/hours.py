"""Time / hours / timezone engine (Bay Area = America/Los_Angeles, UTC-7 in summer).

Parses the time a fan is actually asking about — explicit clock times ("4am", "10:30pm"),
relative phrases ("after midnight", "tonight", "tomorrow morning", "late night"), meals
("breakfast"), and weekdays — in EN/ES/PT, anchored to the match's local day. Then checks a
place's real hours for that weekday/time: open / closed / unknown. We NEVER fall back to a
different day's hours, and NEVER assert open/closed without data.
"""
from __future__ import annotations
import re
from datetime import date

WEEKDAYS3 = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DAY_NAMES = {
    "monday": 0, "mon": 0, "lunes": 0, "segunda": 0, "segunda-feira": 0,
    "tuesday": 1, "tue": 1, "martes": 1, "terça": 1, "terca": 1, "terça-feira": 1,
    "wednesday": 2, "wed": 2, "miércoles": 2, "miercoles": 2, "quarta": 2,
    "thursday": 3, "thu": 3, "jueves": 3, "quinta": 3,
    "friday": 4, "fri": 4, "viernes": 4, "sexta": 4,
    "saturday": 5, "sat": 5, "sábado": 5, "sabado": 5,
    "sunday": 6, "sun": 6, "domingo": 6,
}
MEAL_HOURS = {"breakfast": 8, "desayuno": 8, "café de la mañana": 8, "brunch": 10,
              "lunch": 13, "almuerzo": 13, "almoço": 13, "almoco": 13,
              "dinner": 19, "cena": 19, "jantar": 19, "comida": 13}


def kickoff_weekday(event: dict) -> int:
    iso = (event or {}).get("kickoff_local", "2026-06-27T18:00:00-07:00")
    try:
        return date(int(iso[0:4]), int(iso[5:7]), int(iso[8:10])).weekday()
    except Exception:
        return 5  # Saturday default


def kickoff_hour(event: dict) -> int:
    try:
        return int((event or {}).get("kickoff_local", "T18")[11:13])
    except Exception:
        return 18


def parse_requested_time(text: str, event: dict) -> dict:
    """Return {hour, weekday, label, open_now_question, has_time} in Pacific.

    hour is 0-23 (or None). weekday 0-6 (Mon=0), defaults to the match day.
    """
    t = " " + (text or "").lower() + " "
    base_wd = kickoff_weekday(event)
    weekday, hour, label = base_wd, None, None
    open_now_q = any(p in t for p in [" open now", "open right now", "is it open", "are they open",
                                      "está abierto", "esta abierto", "abierto ahora",
                                      "está aberto", "esta aberto", "aberto agora", "open at this"])

    # weekday words
    for name, idx in DAY_NAMES.items():
        if f" {name} " in t or f" {name}?" in t or f" {name}," in t:
            weekday = idx
            label = name
            break
    if " tomorrow" in t or "mañana" in t or "manana" in t or "amanhã" in t or "amanha" in t:
        weekday = (base_wd + 1) % 7
        label = "tomorrow"
    if " today" in t or " tonight" in t or " hoy " in t or " hoje " in t or "esta noche" in t or "à noite" in t:
        weekday = base_wd

    # explicit clock: "4am", "10:30 pm", "at 7 am", "23:00"
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", t)
    if m:
        h = int(m.group(1)) % 12
        if m.group(3).startswith("p"):
            h += 12
        hour, label = h, m.group(0).strip()
    else:
        m24 = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", t)
        if m24:
            hour, label = int(m24.group(1)), m24.group(0)

    # relative phrases (only if no explicit clock)
    if hour is None:
        if "after midnight" in t or "despues de medianoche" in t or "después de medianoche" in t or \
           "depois da meia-noite" in t or "depois da meia noite" in t or "madrugada" in t:
            hour, label = 1, "after midnight"
        elif "midnight" in t or "medianoche" in t or "meia-noite" in t or "meia noite" in t:
            hour, label = 0, "midnight"
        elif "late night" in t or "late-night" in t or "de noche" in t or "tarde de la noche" in t or \
             "tarde da noite" in t or "alta horas" in t:
            # relative to kickoff: after a 6pm match the late wave is ~21-22, not a literal 11pm
            ko = kickoff_hour(event)
            hour, label = min(23, max(ko + 3, 21)), "late night"
        elif " noon" in t or "mediodía" in t or "mediodia" in t or "meio-dia" in t:
            hour, label = 12, "noon"
        elif " tonight" in t or "esta noche" in t or "à noite" in t or " a noite" in t:
            hour, label = 20, "tonight"
        elif "morning" in t or "mañana por la" in t or "manha" in t or "manhã" in t or "de la mañana" in t:
            hour, label = 9, "morning"
        else:
            for meal, mh in MEAL_HOURS.items():
                if meal in t:
                    hour, label = mh, meal
                    break

    return {"hour": hour, "weekday": weekday, "label": label,
            "open_now_question": open_now_q, "has_time": hour is not None}


def _hm(s: str) -> int | None:
    try:
        return int(str(s)[:2]) * 60 + int(str(s)[3:5] or 0)   # "24:00" -> 1440 (end of day)
    except Exception:
        return None


def _day_intervals(day) -> list:
    """Normalize a day's hours to a list of (open_min, close_min). Supports the official Google
    Places shape via an optional `intervals` list (split hours, e.g. lunch + dinner), a single
    {open, close}, and 24-hour ({open:'00:00', close:'24:00'})."""
    if not day:
        return []
    items = day.get("intervals") if isinstance(day, dict) and day.get("intervals") else [day]
    out = []
    for it in items:
        o, c = _hm((it or {}).get("open")), _hm((it or {}).get("close"))
        if o is not None and c is not None:
            out.append((o, c))
    return out


def _day_open_at(day, hour: int) -> str:
    ivs = _day_intervals(day)
    if not ivs:
        return "unknown"
    minute = hour * 60
    for o, c in ivs:
        if c <= o:  # wraps past midnight (e.g. 18:00 -> 01:00)
            if minute >= o or minute < c:
                return "open"
        elif o <= minute < c:
            return "open"
    return "closed"


def is_open_at(place: dict, weekday: int, hour: int) -> str:
    """'open' | 'closed' | 'unknown' for a place at a given Pacific weekday/hour.

    Never asserts a specific day's hours from another day. BUT if the requested day's hours
    aren't on file, and the place is open at that hour on NONE of the days we *do* know, we
    return 'closed' — we won't send a fan to a 3 a.m. visit at a spot that closes at 21:00
    every day we have data for. Handles after-midnight close (e.g. 01:00)."""
    hours = place.get("hours") or {}
    if place.get("business_status") == "closed":
        return "closed"
    key = WEEKDAYS3[weekday % 7]
    day = hours.get(key)
    if not _day_intervals(day):
        known = [d for d in hours.values() if _day_intervals(d)]
        if known and all(_day_open_at(d, hour) == "closed" for d in known):
            return "closed"   # provably outside the operating envelope on every known day
        return "unknown"
    return _day_open_at(day, hour)


def hours_for_day(place: dict, weekday: int) -> str | None:
    day = (place.get("hours") or {}).get(WEEKDAYS3[weekday % 7])
    if not day:
        return None
    items = day.get("intervals") if isinstance(day, dict) and day.get("intervals") else [day]
    parts = [f"{i['open']}–{i['close']}" for i in items if i.get("open") and i.get("close")]
    if parts == ["00:00–24:00"]:
        return "open 24 hours"
    return ", ".join(parts) or None
