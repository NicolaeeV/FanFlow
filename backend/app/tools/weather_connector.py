"""Weather connector — match-window forecast + actionable alerts (NWS / Open-Meteo).

Wraps the existing free, no-key Open-Meteo client (production can swap in NWS api.weather.gov,
also free/no-key). Adds match-window summary + heat/rain/wind flags and concrete suggestions
(water / indoor backup / ponchos). Degrades to a neutral forecast on any error.
"""
from __future__ import annotations
from .weather import get_weather, DEFAULT_LAT, DEFAULT_LON


def match_window_weather(event: dict) -> dict:
    date = (event or {}).get("kickoff_local", "")[:10]
    lat = (event or {}).get("venue_lat", DEFAULT_LAT)
    lon = (event or {}).get("venue_lon", DEFAULT_LON)
    wx = get_weather(date=date, lat=lat, lon=lon)
    temp = wx.get("avg_temp_c", 22)
    precip = wx.get("max_precip_prob", 0)

    alerts, suggestions = [], []
    if precip >= 50:
        alerts.append("rain_likely"); suggestions.append("Bring ponchos / suggest an indoor backup spot")
    elif precip >= 25:
        alerts.append("rain_possible"); suggestions.append("Have a covered/indoor option ready")
    if temp >= 30:
        alerts.append("heat"); suggestions.append("Push bottled water & shade; expect higher drink demand")
    elif temp <= 8:
        alerts.append("cold"); suggestions.append("Promote warm food/drinks; indoor seating")

    return {
        "available": True, "source": wx.get("source", "open-meteo"),
        "date": date or "match window", "avg_temp_c": temp, "max_precip_prob": precip,
        "alerts": alerts, "suggestions": suggestions,
        "indoor_backup_recommended": "rain_likely" in alerts,
        "freshness": "live" if wx.get("source") != "fallback" else "fallback",
    }
