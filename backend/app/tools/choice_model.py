"""Choice model — utility per place → softmax probability of choosing it.

Humans mostly repeat (comfort) but tourism adds openness to novelty. We score each place
on a comfort utility and a novelty utility, blend them by an exploration weight that
depends on visitor type, then convert to choice probabilities with a softmax temperature.

  Choice ≈ (1-explore)·comfort_fit + explore·novelty   →  softmax(blend / T)
"""
from __future__ import annotations
import math
from .home_score import home_away_score
from .hidden_gem_score import hidden_gem_score

# exploration weight + softmax temperature by visitor type
EXPLORE = {
    "family": {"explore": 0.10, "temp": 0.6},        # exploit comfort/safety
    "nervous_first_time": {"explore": 0.05, "temp": 0.5},
    "solo": {"explore": 0.35, "temp": 0.9},
    "group": {"explore": 0.40, "temp": 1.0},
    "long_stay": {"explore": 0.50, "temp": 1.0},      # most open to discovery
    "default": {"explore": 0.25, "temp": 0.8},
}


def _softmax(vals: list[float], temp: float) -> list[float]:
    if not vals:
        return []
    m = max(vals)
    exp = [math.exp((v - m) / max(temp, 1e-3)) for v in vals]
    z = sum(exp)
    return [e / z for e in exp]


def score_places(places: list[dict], event: dict | None = None, demand_langs: set | None = None,
                 intent_cats: list | None = None, visitor_type: str = "default") -> dict:
    cfg = EXPLORE.get(visitor_type, EXPLORE["default"])
    explore, temp = cfg["explore"], cfg["temp"]
    rows = []
    for b in places:
        home = home_away_score(b, event or {}, demand_langs or set(), "", intent_cats)
        gem = hidden_gem_score(b, event or {}, demand_langs or set(), intent_cats)
        comfort_util = home["home_score"] / 100.0           # trust/convenience/comfort/readiness
        novelty_util = gem["hidden_gem_score"] / 100.0       # authenticity/hidden-gem
        blend = (1 - explore) * comfort_util + explore * novelty_util
        rows.append({
            "business_id": b.get("_id"), "name": b.get("name"), "category": b.get("category"),
            "price_level": b.get("price_level"), "reviews": gem["reviews"],
            "distance_km": home.get("distance_km"),
            "comfort_util": round(comfort_util, 3), "novelty_util": round(novelty_util, 3),
            "blended_utility": round(blend, 3),
            "home_score": home["home_score"], "hidden_gem_score": gem["hidden_gem_score"],
            "is_hidden_gem": gem["is_hidden_gem"], "bayesian_rating": gem["bayesian_rating"],
            "rating_confidence": gem["rating_confidence"],
            "local_sentiment_confidence": gem["local_sentiment_confidence"],
            "review_cues": gem["review_cues"],
            "why": home["why_recommended"][:3],
        })
    probs = _softmax([r["blended_utility"] for r in rows], temp)
    for r, p in zip(rows, probs):
        r["choice_probability"] = round(p, 3)
    rows.sort(key=lambda r: r["choice_probability"], reverse=True)
    return {"visitor_type": visitor_type, "explore_weight": explore, "softmax_temp": temp,
            "ranked": rows}
