"""Special-day hours awareness — World Cup match days and public holidays.

On a big match day or a holiday, a business's REGULAR weekly hours often don't hold: some
extend for the surge, some close early, some get slammed. We will NOT fabricate the special
hours (we don't know them). Instead we recognize the date as special and tell the fan to
confirm — turning "we don't know" into honest, actionable guidance. Regular weekly hours
(now seeded for every day) remain the baseline; this only adds a verify-flag on special days.
"""
from __future__ import annotations
from datetime import date, timedelta

# US public holidays during the 2026 tournament window (Jun 11 – Jul 19) when hours commonly
# change. Keyed (month, day). Extend as needed; this is calendar fact, not fabricated hours.
HOLIDAYS_2026 = {
    (6, 19): "Juneteenth",
    (7, 3): "Independence Day (observed)",
    (7, 4): "Independence Day",
}


def event_date(event: dict) -> date | None:
    iso = (event or {}).get("kickoff_local", "")
    try:
        return date(int(iso[0:4]), int(iso[5:7]), int(iso[8:10]))
    except Exception:
        return None


def date_for_weekday(event: dict, weekday: int) -> date | None:
    """The actual calendar date of a requested weekday within the match week (so 'tomorrow' /
    'sunday' map to a real date we can holiday-check)."""
    d = event_date(event)
    if d is None or weekday is None:
        return None
    return d + timedelta(days=(weekday - d.weekday()))


def holiday_name(d: date | None) -> str | None:
    return HOLIDAYS_2026.get((d.month, d.day)) if d else None


def place_special_on(place: dict, event: dict, requested_time: dict | None = None) -> bool:
    """Does THIS place list official Google Places special hours (a SpecialDay) for the day the
    fan is asking about? (Per-place, from live data — distinct from calendar holidays.)"""
    dates = (place or {}).get("special_hours_dates") or []
    if not dates:
        return False
    wd = (requested_time or {}).get("weekday")
    asked = date_for_weekday(event, wd) if wd is not None else event_date(event)
    return bool(asked and asked.isoformat() in dates)


def special_day_info(event: dict, requested_time: dict | None = None) -> dict:
    """Is the day the fan is asking about a match day and/or a holiday? Returns flags + a
    confirm note. Defaults to the match day when no specific day was asked."""
    md = event_date(event)
    wd = (requested_time or {}).get("weekday")
    asked = date_for_weekday(event, wd) if wd is not None else md
    is_match_day = bool(md and asked == md)
    holiday = holiday_name(asked)
    note = None
    if holiday:
        note = {
            "en": f"Heads up: that day is {holiday} — holiday hours often differ, so confirm before you go.",
            "es": f"Aviso: ese día es {holiday} — los horarios de feriado suelen cambiar, confírmalo antes de ir.",
            "pt": f"Atenção: esse dia é {holiday} — horários de feriado costumam mudar, confirme antes de ir.",
        }
    elif is_match_day:
        note = {
            "en": "On match day some spots extend hours and others close early or fill up — I've flagged what I can't confirm; call ahead to be sure.",
            "es": "En día de partido algunos lugares amplían horarios y otros cierran temprano o se llenan — marqué lo que no puedo confirmar; llama para asegurarte.",
            "pt": "Em dia de jogo alguns lugares estendem o horário e outros fecham cedo ou lotam — sinalizei o que não posso confirmar; ligue para confirmar.",
        }
    return {
        "is_match_day": is_match_day,
        "holiday": holiday,
        "date": asked.isoformat() if asked else None,
        "special": bool(holiday or is_match_day),
        "note": note,
    }
