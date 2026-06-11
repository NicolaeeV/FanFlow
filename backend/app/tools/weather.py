"""get_weather — hourly temp/precip modifier from Open-Meteo (free, no key).

Returns a small dict the forecast model uses to nudge foot-traffic and inventory
(e.g. higher precip -> ponchos/umbrellas up, patio traffic down).
"""
from __future__ import annotations
from functools import lru_cache
import httpx

# Default to Santa Clara / Levi's Stadium area.
DEFAULT_LAT, DEFAULT_LON = 37.4033, -121.9694


@lru_cache(maxsize=512)
def get_weather(city: str = "bay_area", date: str = "", lat: float = DEFAULT_LAT,
                lon: float = DEFAULT_LON) -> dict:
    """Hourly forecast around a venue. `date` is YYYY-MM-DD (optional). Memoized."""
    try:
        params = {
            "latitude": lat, "longitude": lon,
            "hourly": "temperature_2m,precipitation_probability,precipitation",
            "temperature_unit": "celsius", "timezone": "America/Los_Angeles",
        }
        if date:
            params["start_date"] = date
            params["end_date"] = date
        # 6s (not 10): weather is a minor signal with a clean fallback. A cold first call shouldn't
        # stall an agent turn for 10s — degrade to the neutral fallback faster if the API is slow.
        r = httpx.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=6)
        r.raise_for_status()
        h = r.json().get("hourly", {})
        temps = h.get("temperature_2m", []) or [20]
        precip = h.get("precipitation_probability", []) or [0]
        max_precip = max(precip) if precip else 0
        avg_temp = round(sum(temps) / len(temps), 1) if temps else 20
        # modifier: rain depresses walk-in traffic; heat slightly depresses too.
        weather_mod = 1.0
        if max_precip >= 50:
            weather_mod = 0.88
        elif max_precip >= 25:
            weather_mod = 0.95
        if avg_temp >= 32:
            weather_mod *= 0.96
        return {
            "city": city, "date": date or "next_24h",
            "avg_temp_c": avg_temp, "max_precip_prob": max_precip,
            "weather_mod": round(weather_mod, 3),
            "inventory_hint": "rain_gear" if max_precip >= 40 else ("hydration" if avg_temp >= 30 else "none"),
            "source": "open-meteo",
        }
    except Exception as e:  # resilient demo fallback
        return {"city": city, "date": date, "avg_temp_c": 22, "max_precip_prob": 10,
                "weather_mod": 1.0, "inventory_hint": "none", "source": "fallback", "error": str(e)}
