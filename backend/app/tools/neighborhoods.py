"""Neighborhood / vicinity model — the single source of truth for "where fans are and
what's realistic around a match" — now CONFIG-DRIVEN for multi-city scaling.

Each neighborhood carries real local knowledge: where it sits relative to the stadium, how
you actually get there (walk / transit / drive), and whether it's realistic BEFORE, AFTER,
or LATE relative to a match — so recommendations reason like a local guide, not just a
distance circle. Coordinates are approximate centroids; verify against official 2026 maps.
This module ADDS no businesses — it only describes areas that already exist.

MULTI-CITY: zone definitions live in backend/config/cities/<city>.json (Bay Area today;
clone the file per host city — same schema, new zones). Select via MATCHDAY_CITY env
(default "bay_area"). The Python API is unchanged.
"""
from __future__ import annotations
import json
import os
import pathlib
from ._geo import haversine_km

_CITIES_DIR = pathlib.Path(__file__).resolve().parents[2] / "config" / "cities"
DEFAULT_CITY = "bay_area"


def _load_city(city_id: str | None = None) -> dict:
    cid = (city_id or os.getenv("MATCHDAY_CITY") or DEFAULT_CITY).strip()
    path = _CITIES_DIR / f"{cid}.json"
    if not path.exists():                      # unknown city -> fall back, never crash
        path = _CITIES_DIR / f"{DEFAULT_CITY}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def available_cities() -> list:
    return sorted(p.stem for p in _CITIES_DIR.glob("*.json"))


_CITY = _load_city()
CITY_ID = _CITY["city_id"]
CITY_NAME = _CITY["city_name"]
# the stadium anchor for this city (e.g. Levi's Stadium for bay_area)
STADIUM = (_CITY["stadium"]["lat"], _CITY["stadium"]["lon"])
STADIUM_NAME = _CITY["stadium"]["name"]
# tier: stadium_adjacent ≤ ~6km · near ≤ ~12km · mid ≤ ~20km · far > 20km
# realism per stage: "great" | "ok" | "tight" | "poor"
NEIGHBORHOODS = _CITY["neighborhoods"]

_STAGE_TO_KEY = {
    "pre_match_food": "pre_match", "pre_match_drinks": "pre_match", "family_meal": "pre_match",
    "stadium_arrival": "pre_match", "post_match_celebration": "post_match",
    "watch_party_no_ticket": "post_match", "soccer_fan_spot": "post_match",
    "late_night_food": "late_night", "next_day_local": "pre_match", "parking_transit": "pre_match",
}
_TIER_LABEL = {
    "en": {"stadium_adjacent": "right by the stadium", "near": "a short hop from Levi's",
           "mid": "a longer trip from Levi's", "far": "well out from Levi's"},
    "es": {"stadium_adjacent": "junto al estadio", "near": "a un paso de Levi's",
           "mid": "un trayecto más largo desde Levi's", "far": "lejos de Levi's"},
    "pt": {"stadium_adjacent": "ao lado do estádio", "near": "pertinho do Levi's",
           "mid": "um trajeto mais longo do Levi's", "far": "longe do Levi's"},
}
_MODE_LABEL = {
    "en": {"walk": "Walk", "drive": "Drive", "vta": "VTA", "ace": "ACE", "caltrain": "Caltrain", "bart": "BART"},
    "es": {"walk": "a pie", "drive": "en coche", "vta": "VTA", "ace": "ACE", "caltrain": "Caltrain", "bart": "BART"},
    "pt": {"walk": "a pé", "drive": "de carro", "vta": "VTA", "ace": "ACE", "caltrain": "Caltrain", "bart": "BART"},
}
_STRETCH = {
    "en": {"tight": " · a stretch for this time", "poor": " · not ideal this late"},
    "es": {"tight": " · un poco lejos para esta hora", "poor": " · no ideal tan tarde"},
    "pt": {"tight": " · um pouco longe para esse horário", "poor": " · não ideal tão tarde"},
}


def get_neighborhood(nb_id: str) -> dict | None:
    return NEIGHBORHOODS.get(nb_id)


def centroid(nb_id: str):
    nb = NEIGHBORHOODS.get(nb_id)
    return (nb["lat"], nb["lon"]) if nb else None


def distance_to_stadium_km(nb_id: str) -> float | None:
    nb = NEIGHBORHOODS.get(nb_id)
    if not nb:
        return None
    return round(haversine_km(nb["lat"], nb["lon"], *STADIUM), 1)


def drive_base_min(nb_id: str):
    nb = NEIGHBORHOODS.get(nb_id)
    return nb["drive_base_min"] if nb else None


def access_modes(nb_id: str) -> list:
    nb = NEIGHBORHOODS.get(nb_id)
    return list(nb["access"]) if nb else []


def realistic_for_stage(nb_id: str, stage: str | None) -> str:
    """'great' | 'ok' | 'tight' | 'poor' | 'unknown' — is this area sensible at this stage?"""
    nb = NEIGHBORHOODS.get(nb_id)
    if not nb:
        return "unknown"
    return nb.get(_STAGE_TO_KEY.get(stage or "", "pre_match"), "ok")


def nearest_neighborhood(lat, lon) -> str | None:
    if lat is None or lon is None:
        return None
    best, bestd = None, 1e9
    for nb_id, nb in NEIGHBORHOODS.items():
        d = haversine_km(lat, lon, nb["lat"], nb["lon"])
        if d < bestd:
            best, bestd = nb_id, d
    return best


def vicinity_label(nb_id: str, stage: str | None = None, lang: str = "en") -> str | None:
    """A short local-guide phrase (localized): which area, how you get there, and a
    stage-realism hint. Area names are proper nouns and kept as-is."""
    nb = NEIGHBORHOODS.get(nb_id)
    if not nb:
        return None
    lang = lang if lang in _TIER_LABEL else "en"
    access = "/".join(_MODE_LABEL[lang].get(m, m.upper()) for m in nb["access"][:2])
    phrase = f"{nb['name']} — {_TIER_LABEL[lang][nb['tier']]}, {access}"
    fit = realistic_for_stage(nb_id, stage)
    if stage and fit in ("tight", "poor"):
        phrase += _STRETCH[lang][fit]
    return phrase
