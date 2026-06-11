"""Demand sensing — aggregate behavior change from Google Analytics / GBP / Trends.

This is the evidence layer. It NEVER identifies individuals; it compares an aggregate
baseline window to the match window ("Normal Friday 4-8 PM vs Mexico-match Friday
4-8 PM") and reports deltas. Real GA4/GBP require owner-connected OAuth; the MVP reads
seeded deltas and degrades to "no first-party signal yet" so intents stay honest.
"""
from __future__ import annotations
from .. import mongo


def _delta(base: dict, win: dict, key: str) -> dict:
    b, w = base.get(key, 0), win.get(key, 0)
    return {
        "baseline": b, "match_window": w,
        "delta_pct": round((w - b) / b * 100) if b else None,
        "ratio": round(w / b, 2) if b else None,
    }


def get_visitor_signals(business_id: str, match_id: str) -> dict:
    """Baseline-vs-match-window aggregate signals (GA4-style) for a business."""
    sig = mongo.get_intent_signals(business_id, match_id)
    if not sig:
        return {
            "business_id": business_id, "match_id": match_id, "available": False,
            "note": "No first-party GA4/GBP signals connected for this business yet. "
                    "Visitor intents will be presented as low-confidence hypotheses until "
                    "the owner connects Google Analytics / Business Profile to confirm them.",
        }
    base, win = sig.get("baseline", {}), sig.get("match_window", {})
    deltas = {k: _delta(base, win, k) for k in
              ["sessions", "menu_clicks", "direction_clicks", "call_clicks", "reservation_clicks"]}
    es_base, es_win = base.get("es_session_ratio"), win.get("es_session_ratio")
    return {
        "business_id": business_id, "match_id": match_id, "available": True,
        "window_label": sig.get("window_label"),
        "deltas": deltas,
        "es_session_ratio": {
            "baseline": es_base, "match_window": es_win,
            "ratio": round(es_win / es_base, 2) if es_base else None,
        },
        "trends": sig.get("trends", {}),
        "gbp": sig.get("gbp", {}),
        "source": sig.get("source"),
        "note": "Aggregate window comparison only — never individual identification.",
    }
