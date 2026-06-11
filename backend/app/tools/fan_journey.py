"""Fan journey model — recommendations depend on the soccer trip stage.

A pub is wrong for a peanut-allergy family pre-match; a taqueria great before the match may
be closed post-match; a watch-party spot matters for non-ticket fans. Each stage maps to
preferred place types, the open-hours window that must be viable, whether to exclude bars
for families, and how much soccer relevance matters.
"""
from __future__ import annotations

PRE_FOOD = "pre_match_food"
PRE_DRINKS = "pre_match_drinks"
FAMILY_MEAL = "family_meal"
PARKING_TRANSIT = "parking_transit"
STADIUM_ARRIVAL = "stadium_arrival"
POST_CELEBRATION = "post_match_celebration"
LATE_NIGHT = "late_night_food"
WATCH_PARTY = "watch_party_no_ticket"
NEXT_DAY = "next_day_local"
SOCCER_FANS = "soccer_fan_spot"   # "where do real soccer fans go?"

STAGE_POLICY = {
    PRE_FOOD: {"window": "pre", "exclude_family_bars": False, "soccer_weight": 0.1},
    PRE_DRINKS: {"window": "pre", "exclude_family_bars": False, "soccer_weight": 0.4},
    FAMILY_MEAL: {"window": "pre", "exclude_family_bars": True, "soccer_weight": 0.0},
    PARKING_TRANSIT: {"window": "any", "exclude_family_bars": False, "soccer_weight": 0.0},
    STADIUM_ARRIVAL: {"window": "pre", "exclude_family_bars": False, "soccer_weight": 0.1},
    POST_CELEBRATION: {"window": "post", "exclude_family_bars": False, "soccer_weight": 0.6},
    LATE_NIGHT: {"window": "late", "exclude_family_bars": False, "soccer_weight": 0.1},
    WATCH_PARTY: {"window": "post", "exclude_family_bars": False, "soccer_weight": 1.0},
    NEXT_DAY: {"window": "any", "exclude_family_bars": False, "soccer_weight": 0.0},
    SOCCER_FANS: {"window": "post", "exclude_family_bars": False, "soccer_weight": 1.0},
}

_NO_TICKET = ["no ticket", "without ticket", "without a ticket", "don't have ticket",
              "dont have ticket", "don't have a ticket", "dont have a ticket", "no tickets",
              "sin boleto", "sin boletos", "sin entradas", "no entrada", "não tenho ingresso",
              "watch party", "watch-party", "where to watch the game"]
# NOTE: generic "watch the game" is NOT here — with a named venue ("sports bar to watch
# the game") the fan wants a place rec, not a no-ticket watch-party route.
_SOCCER_FANS = ["where do soccer fans", "where do real soccer fans", "soccer fans go",
                "real fans", "fans go after", "where do fans", "supporters go", "fan bar"]


def detect_stage(text: str, slots: dict, party_family: bool) -> str:
    t = (text or "").lower()
    timing = slots.get("timing")
    if any(p in t for p in _SOCCER_FANS):
        return SOCCER_FANS
    if any(p in t for p in _NO_TICKET):
        return WATCH_PARTY
    if "next day" in t or "day off" in t or "sightseeing" in t or "tomorrow" in t:
        return NEXT_DAY
    if slots.get("transport") and ("park" in t or "parking" in t):
        return PARKING_TRANSIT
    if timing == "late_night":
        return LATE_NIGHT
    if timing == "post_match":
        return POST_CELEBRATION
    if party_family:
        return FAMILY_MEAL
    if timing == "pre_match" and ("drink" in t or "beer" in t or "pub" in t or "cerveza" in t):
        return PRE_DRINKS
    return PRE_FOOD
