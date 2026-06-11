"""Bayesian visitor-intent model.

Cravings are stable; context shifts them. Start from a prior over intents, then update
with log-likelihoods as the fan talks and as signals arrive. Output a posterior +
confidence, and — if confidence is low — the single most informative follow-up to ask.

No identity/ethnicity inference. Cues are words the visitor chose + aggregate match
context, never protected attributes.
"""
from __future__ import annotations
import math

INTENTS = ["comfort", "convenience", "family", "local_authenticity", "language_comfort",
           "celebration", "late_night", "parking_transit", "novelty"]

PRIOR = {"comfort": 0.20, "convenience": 0.18, "family": 0.14, "local_authenticity": 0.14,
         "language_comfort": 0.08, "celebration": 0.10, "late_night": 0.06,
         "parking_transit": 0.05, "novelty": 0.05}

# cue -> {intent: log-likelihood-ratio boost}. Positive raises that intent's posterior.
CUES = {
    "kid": {"family": 2.4, "celebration": -1.4, "late_night": -1.2, "comfort": 0.4},
    "family": {"family": 2.2, "celebration": -1.0, "comfort": 0.4},
    "after": {"late_night": 1.2, "celebration": 0.8},
    "late": {"late_night": 1.4, "celebration": 0.6},
    "before": {"convenience": 0.8, "comfort": 0.4},
    "authentic": {"local_authenticity": 1.5, "novelty": 0.8},
    "local": {"local_authenticity": 1.3, "novelty": 0.5},
    "hidden": {"local_authenticity": 1.2, "novelty": 1.0},
    "drive": {"parking_transit": 1.2},
    "parking": {"parking_transit": 1.6},
    "vta": {"parking_transit": 1.0, "convenience": 0.6},
    "caltrain": {"parking_transit": 1.0, "convenience": 0.6},
    "transit": {"parking_transit": 1.0, "convenience": 0.6},
    "quick": {"convenience": 1.4},
    "easy": {"convenience": 1.0},
    "pub": {"celebration": 1.5, "family": -0.8},
    "bar": {"celebration": 1.3, "family": -0.8},
    "drinks": {"celebration": 1.3},
    "watch party": {"celebration": 1.2},
    "coffee": {"comfort": 1.0, "convenience": 0.6},
    "taco": {"comfort": 0.8, "language_comfort": 0.6},
    "spanish": {"language_comfort": 1.6},
    "español": {"language_comfort": 1.6},
}

# follow-ups, each tagged with which intents it best disambiguates
FOLLOWUPS = [
    {"q": "Are you eating before the match, after, or both?", "splits": ["convenience", "late_night", "celebration"]},
    {"q": "Are you driving, taking VTA/Caltrain, or staying near San José?", "splits": ["parking_transit", "convenience"]},
    {"q": "Looking for a quick easy bite, or a real local sit-down experience?", "splits": ["convenience", "local_authenticity", "novelty"]},
]


def _softmax(logits: dict) -> dict:
    m = max(logits.values())
    exp = {k: math.exp(v - m) for k, v in logits.items()}
    z = sum(exp.values())
    return {k: v / z for k, v in exp.items()}


def infer_visitor_intent(query: str, match_id: str = "", answers: dict | None = None,
                         es_demand: float = 0.0) -> dict:
    """Posterior over visitor intents from the query + answers + aggregate match context."""
    text = " ".join([query or "", " ".join((answers or {}).values())]).lower()
    logits = {k: math.log(max(PRIOR[k], 1e-6)) for k in INTENTS}
    fired = []
    for cue, boosts in CUES.items():
        if cue in text:
            fired.append(cue)
            for intent, b in boosts.items():
                logits[intent] += b
    # aggregate match context: a high non-English (es) demand nudges language_comfort
    if es_demand >= 0.3:
        logits["language_comfort"] += 1.0
        fired.append(f"aggregate es-demand={es_demand}")

    posterior = _softmax(logits)
    ranked = sorted(posterior.items(), key=lambda x: -x[1])
    top, conf = ranked[0][0], round(ranked[0][1], 2)

    # pick the most informative follow-up if we're not confident yet
    followup = None
    if conf < 0.55 and not (answers or {}):
        # choose the follow-up whose split intents are currently most ambiguous (near-tied)
        followup = max(FOLLOWUPS, key=lambda f: sum(posterior.get(i, 0) for i in f["splits"]))["q"]

    return {
        "match_id": match_id,
        "posterior": {k: round(v, 3) for k, v in ranked},
        "top_intent": top, "confidence": conf,
        "cues_fired": fired,
        "needs_followup": followup is not None,
        "suggested_followup": followup,
        "note": "Bayesian update from the visitor's own words + aggregate match context. No identity inference.",
    }
