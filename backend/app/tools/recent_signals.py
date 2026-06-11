"""Recent-signal tracking ('what changed in the last ~30 days').

Pattern adapted from the last30days skill (pull recent posts/engagement across sources
to see what's actually rising NOW). Here it surfaces recent demand shifts for a host
city/match: rising query clusters, newly-listed watch parties, and trending fan topics.
Seeded for the MVP; production wires Trends/Search Console/social deltas + a scrape of
new event listings.
"""
from __future__ import annotations
from .. import mongo

# Seeded 'recent change' snapshot (illustrative). Production computes these from
# real 30-day deltas across Trends / Search Console / event-listing scrapes.
_RISING = {
    "wc26_mex_ksa_2026-06-27": {
        "rising_queries": [
            {"cluster": "late night food near Levi's", "trend_30d_pct": 210},
            {"cluster": "comida cerca del estadio (ES)", "trend_30d_pct": 320},
            {"cluster": "world cup watch party san jose", "trend_30d_pct": 180},
            {"cluster": "parking near Levi's Stadium", "trend_30d_pct": 140},
            {"cluster": "authentic tacos San Jose", "trend_30d_pct": 95},
        ],
        "new_watch_parties_30d": ["San Pedro Square Market (candidate)"],
        "trending_fan_topics": ["Mexico group-stage demand", "VTA service for match days", "Spanish-language menus"],
    }
}


def recent_demand_changes(match_id: str) -> dict:
    """Surface what's risen in roughly the last 30 days for this match/city."""
    snap = _RISING.get(match_id)
    ev = mongo.get_event(match_id) or {}
    if not snap:
        return {
            "match_id": match_id, "available": False,
            "note": "No recent-signal snapshot for this match yet. Production wires Trends / "
                    "Search Console / event-listing scrapes for a live 30-day delta.",
        }
    return {
        "match_id": match_id, "city_id": ev.get("city_id"), "window_days": 30,
        **snap,
        "method": "Adapted from the last30days recency pattern — rising query clusters + newly "
                  "listed fan venues over ~30 days. Seeded here; live deltas in production.",
    }
