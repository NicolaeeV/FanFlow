"""Soccer relevance layer.

Labels a place by how soccer-relevant it is, gated by evidence. We NEVER assert "classic
soccer pub", "historic soccer bar", or "home of the fans" unless a source supports it.

Labels: verified_soccer_hub | candidate_soccer_spot | general_sports_bar | not_soccer_specific
"""
from __future__ import annotations
from .. import mongo
from .review_understanding import analyze_reviews
from .claim_validator import validate_claim

VERIFIED_HUB = "verified_soccer_hub"
CANDIDATE = "candidate_soccer_spot"
GENERAL_BAR = "general_sports_bar"
NOT_SPECIFIC = "not_soccer_specific"

SOCCER_WORDS = ("soccer", "fútbol", "futbol", "football", "premier league", "world cup",
                "watch party", "matchday", "supporters")


def soccer_relevance(place: dict, context: dict | None = None) -> dict:
    context = context or {}
    bid = place.get("_id", "")
    evidence, label, source = [], NOT_SPECIFIC, None

    # 1) official watch-party / soccer venue (fan_venues, sourced + candidate-labeled)
    fv = next((v for v in mongo.get_fan_venues() if v["_id"] == bid or v.get("business_id") == bid), None)
    if fv:
        evidence.append({"type": "fan_venue", "venue_type": fv.get("type"), "source": fv.get("source"),
                         "status": "candidate" if fv.get("candidate") else "confirmed"})
        source = "official_event"
        label = VERIFIED_HUB if not fv.get("candidate") else CANDIDATE

    # 2) review/source text mentions soccer (candidate signal only)
    rev = analyze_reviews(bid)
    text = " ".join(s for s in [str(rev.get("cues"))]).lower()
    if rev.get("available") and ("soccer" in rev.get("cues", {})):
        evidence.append({"type": "review_cue", "cue": "soccer", "source": rev.get("source")})
        if label == NOT_SPECIFIC:
            label, source = CANDIDATE, "reddit_public_post"

    # 3) category / attribute signals (general only — not soccer-specific proof)
    cat = place.get("category", "")
    attrs = set((place.get("gbp", {}) or {}).get("attributes", []))
    if label == NOT_SPECIFIC and (cat in ("sports_bar", "bar") or "live_sports" in attrs):
        label, source = GENERAL_BAR, "seed"
        evidence.append({"type": "category", "value": cat or "live_sports"})

    # validate the soccer-pub claim through the source policy (never invent reputation)
    claim = validate_claim("soccer_pub", source_type=source) if source else \
        {"allowed": False, "label": "needs_verification"}
    score = {VERIFIED_HUB: 1.0, CANDIDATE: 0.7, GENERAL_BAR: 0.45, NOT_SPECIFIC: 0.0}[label]

    return {
        "business_id": bid, "label": label, "score": score,
        "evidence": evidence, "source": source,
        "claim_allowed": claim["allowed"],   # may we *assert* a soccer-pub claim?
        "user_facing_note": {
            VERIFIED_HUB: "Verified soccer/watch spot (official source).",
            CANDIDATE: "Candidate soccer spot — mentioned for soccer/watch parties; verify screenings.",
            GENERAL_BAR: "General sports bar — may show the game; confirm it's on.",
            NOT_SPECIFIC: "Not specifically a soccer spot.",
        }[label],
        "disclaimer": "Never described as a 'classic/historic soccer pub' or 'home of the fans' "
                      "without an official source.",
    }
