"""Markov trip-stage model.

The next thing a fan needs depends mostly on where they are in the trip now, not their
whole history. We encode trip stages as states and transition probabilities that differ
by visitor type (family / solo / group / long-stay). Used to recommend by TRIP STAGE,
not just distance.
"""
from __future__ import annotations

STATES = ["airport", "hotel", "pre_match_food", "transit", "stadium",
          "post_match_food", "pub_celebration", "late_night", "return_hotel"]

# transition_probabilities[visitor_type][from_state] -> {to_state: p}
TRANSITIONS = {
    "family": {
        "hotel": {"pre_match_food": 0.6, "transit": 0.3, "stadium": 0.1},
        "pre_match_food": {"transit": 0.5, "stadium": 0.5},
        "transit": {"stadium": 1.0},
        "stadium": {"post_match_food": 0.6, "return_hotel": 0.4},
        "post_match_food": {"return_hotel": 0.9, "late_night": 0.1},
    },
    "solo": {
        "hotel": {"pub_celebration": 0.4, "pre_match_food": 0.4, "transit": 0.2},
        "pre_match_food": {"transit": 0.6, "pub_celebration": 0.4},
        "transit": {"stadium": 1.0},
        "stadium": {"pub_celebration": 0.5, "post_match_food": 0.3, "late_night": 0.2},
        "pub_celebration": {"late_night": 0.5, "return_hotel": 0.5},
    },
    "group": {
        "hotel": {"pub_celebration": 0.6, "pre_match_food": 0.3, "transit": 0.1},
        "pre_match_food": {"pub_celebration": 0.5, "transit": 0.5},
        "transit": {"stadium": 1.0},
        "stadium": {"pub_celebration": 0.6, "late_night": 0.3, "post_match_food": 0.1},
        "pub_celebration": {"late_night": 0.6, "post_match_food": 0.2, "return_hotel": 0.2},
    },
    "long_stay": {
        "hotel": {"pre_match_food": 0.4, "transit": 0.3, "pub_celebration": 0.3},
        "pre_match_food": {"transit": 0.6, "pub_celebration": 0.4},
        "transit": {"stadium": 1.0},
        "stadium": {"post_match_food": 0.5, "pub_celebration": 0.4, "late_night": 0.1},
        "post_match_food": {"return_hotel": 0.7, "late_night": 0.3},
    },
}

# which place categories serve each state
STATE_NEEDS = {
    "pre_match_food": ["mexican_restaurant", "cafe", "taqueria", "convenience_store", "american_restaurant"],
    "post_match_food": ["mexican_restaurant", "american_restaurant", "vietnamese_restaurant", "sports_bar"],
    "pub_celebration": ["sports_bar", "bar"],
    "late_night": ["sports_bar", "mexican_restaurant", "convenience_store"],
    "transit": ["parking", "parking_lot"],
}


def next_state(current: str, visitor_type: str = "solo") -> dict:
    table = TRANSITIONS.get(visitor_type, TRANSITIONS["solo"])
    dist = table.get(current, {})
    if not dist:
        return {"current": current, "visitor_type": visitor_type, "next_distribution": {}, "most_likely_next": None}
    nxt = max(dist, key=dist.get)
    return {"current": current, "visitor_type": visitor_type,
            "next_distribution": dist, "most_likely_next": nxt,
            "needs": STATE_NEEDS.get(nxt, [])}


def predict_trip(visitor_type: str = "family", start: str = "hotel", steps: int = 4) -> dict:
    """Walk the most-likely path forward from a start state."""
    path, cur = [start], start
    for _ in range(steps):
        nxt = next_state(cur, visitor_type)["most_likely_next"]
        if not nxt or nxt in path:
            break
        path.append(nxt)
        cur = nxt
    return {"visitor_type": visitor_type, "likely_path": path,
            "stage_needs": {s: STATE_NEEDS.get(s, []) for s in path if s in STATE_NEEDS}}
