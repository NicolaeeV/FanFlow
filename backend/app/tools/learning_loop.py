"""Learning loop — close the loop with outcomes.

After a recommendation, the app logs what the user actually did (clicked, saved, got
directions, viewed menu, ordered/reserved, reviewed). Those outcomes nudge the priors
and place scores over time, so recommendations improve. MVP stores events + returns
aggregate adjustments; production feeds them back into the Bayesian prior + choice model.
"""
from __future__ import annotations
from .. import mongo

VALID_ACTIONS = {"impression", "click", "save", "directions", "menu_view",
                 "order", "reservation", "review", "thumbs_up", "thumbs_down"}
# how strongly each action signals a good match (for prior nudging)
ACTION_WEIGHT = {"impression": 0.0, "click": 0.3, "menu_view": 0.5, "save": 0.7,
                 "directions": 0.8, "reservation": 1.0, "order": 1.0,
                 "review": 0.9, "thumbs_up": 1.0, "thumbs_down": -1.0}


def log_feedback(session_id: str, action: str, business_id: str = "",
                 match_id: str = "", intent: str = "") -> dict:
    action = action if action in VALID_ACTIONS else "click"
    event = {"session_id": session_id, "action": action, "business_id": business_id,
             "match_id": match_id, "intent": intent, "weight": ACTION_WEIGHT.get(action, 0.3)}
    res = mongo.log_feedback(event)
    return {"logged": event, **res,
            "note": "Outcome recorded. Aggregated outcomes nudge intent priors + place scores over time."}


def learned_adjustments() -> dict:
    """Aggregate outcomes into simple, explainable nudges."""
    counts = mongo.get_feedback_counts()
    # places with strong positive outcomes get a small future boost
    boosts = {bid: round(min(0.15, n * 0.02), 3) for bid, n in counts.get("by_business", {}).items()}
    return {
        "feedback_counts": counts,
        "place_score_boosts": boosts,
        "note": "Illustrative learning loop: positive outcomes (directions/orders/saves) raise a "
                "place's future ranking slightly; thumbs_down lowers it. Production updates the "
                "Bayesian prior + choice-model utilities directly.",
    }
