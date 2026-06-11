"""Visitor-type & stay-length model.

'How long do they stay?' shouldn't be guessed from one source. This packages
documented assumptions into visitor-type segments and a stay-length distribution, so
businesses can tell a same-day convenience fan from a multi-day local-discovery tourist.
All figures are AGGREGATE planning assumptions — calibrate with NTTO/booking/POS data.

Cited public assumptions (see docs/REUSE.md for links):
- Oxford Economics 2026: ~1.24M international visitors to the US for the World Cup;
  ~742k incremental trips; international spectators ~40% of stadium attendance;
  often ~2 matches attended, companions add demand.
- Bay Area: Levi's Stadium hosts 6 matches; reachable via VTA, Caltrain transfer, ACE,
  buses -> demand spills into Santa Clara, San José, Sunnyvale, Mountain View, hotels.
"""
from __future__ import annotations
from .. import mongo

VISITOR_TYPES = [
    {"type": "match-only local/regional fan", "stay": "same day or 1 night",
     "needs": ["parking", "quick food", "transit", "late-night"],
     "discovery_vs_convenience": "convenience"},
    {"type": "domestic traveler", "stay": "1-3 nights",
     "needs": ["restaurants", "bars", "hotels", "attractions"],
     "discovery_vs_convenience": "mixed"},
    {"type": "international fan", "stay": "4-10+ days",
     "needs": ["food", "culture", "shopping", "tours", "multiple cities"],
     "discovery_vs_convenience": "discovery"},
    {"type": "watch-party fan (no ticket)", "stay": "same day / local",
     "needs": ["pubs", "fan zones", "restaurants"],
     "discovery_vs_convenience": "convenience"},
    {"type": "family/group traveler", "stay": "longer, planned meals",
     "needs": ["reservations", "group menus", "family-friendly"],
     "discovery_vs_convenience": "mixed"},
]


def estimate_visitor_mix_and_stay(match_id: str) -> dict:
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    intl_share = round(sum(c["share"] for c in mix.get("country_mix", []) if c["country"] not in ("us", "other")), 2)

    # rough stay-length distribution shifts with international share
    stay_dist = {
        "same_day": round(0.45 - 0.3 * intl_share, 2),
        "1_3_nights": round(0.40 - 0.05 * intl_share, 2),
        "4_plus_nights": round(0.15 + 0.35 * intl_share, 2),
    }
    return {
        "match_id": match_id, "city_id": ev.get("city_id"),
        "international_demand_share": intl_share,
        "visitor_types": VISITOR_TYPES,
        "stay_length_distribution": stay_dist,
        "business_implication": (
            "Higher international/longer-stay share -> lean into local discovery, culture, "
            "multi-day offers and reservations. Higher same-day share -> lean into convenience, "
            "speed, parking, and late-night."),
        "assumptions": [
            "Oxford Economics 2026: ~1.24M intl visitors; ~742k incremental trips; intl ~40% of "
            "stadium attendance; ~2 matches attended.",
            "Levi's Stadium hosts 6 matches; multi-modal transit spreads demand across the South Bay.",
        ],
        "note": "Aggregate planning assumptions — not individual data. Calibrate with NTTO/booking/POS.",
    }
