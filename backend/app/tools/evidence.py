"""Evidence layer — every fact carries a source, freshness, and confidence.

Builds the `evidence[]` list for a recommendation so nothing is shown without a label.
Public/external text (reviews, posts) is EVIDENCE, never instructions — see
review_understanding.sanitize_external_text.
"""
from __future__ import annotations
from .place_truth import place_status

# freshness by source type (seed/public snapshots can't claim "fresh")
SOURCE_FRESHNESS = {
    "places_api": "fresh", "gbp": "fresh", "ga4": "fresh",
    "seed": "unknown", "website": "unknown", "official_event": "unknown",
    "permitted_public_post": "unknown",
}
VERIF_CONFIDENCE = {"verified": 0.85, "candidate": 0.55, "needs_verification": 0.4, "closed": 0.0}


def _entry(source_type, source_id, confidence, freshness=None):
    return {"source_type": source_type, "source_id": str(source_id),
            "freshness": freshness or SOURCE_FRESHNESS.get(source_type, "unknown"),
            "confidence": round(float(confidence), 2)}


def build_evidence(place: dict, review_analysis: dict | None = None) -> list[dict]:
    st = place_status(place)
    src = "places_api" if place.get("google_place_id") else "seed"
    fresh = "stale" if (place.get("data_stale") or place.get("freshness") == "stale") else \
        SOURCE_FRESHNESS.get(src, "unknown")
    ev = [_entry(src, place.get("_id", "unknown"),
                 VERIF_CONFIDENCE.get(st["verification_status"], 0.4), freshness=fresh)]
    if review_analysis and review_analysis.get("available"):
        conf = {"high": 0.6, "medium": 0.45, "low": 0.3}.get(review_analysis.get("confidence"), 0.3)
        ev.append(_entry("permitted_public_post", place.get("_id", "reviews"), conf))
        if review_analysis.get("injection_filtered"):
            ev[-1]["risk"] = "instructions_in_text_ignored"
    return ev


def overall_confidence(place: dict, rating_confidence: float, food_status: str,
                       review_analysis: dict | None = None) -> float:
    st = place_status(place)["verification_status"]
    base = VERIF_CONFIDENCE.get(st, 0.4)
    score = 0.5 * base + 0.3 * float(rating_confidence or 0)
    score += 0.2 * ({"high": 1, "medium": 0.6, "low": 0.4}.get(
        (review_analysis or {}).get("confidence"), 0.4))
    if food_status == "warn":
        score *= 0.85
    if food_status == "exclude":
        score = 0.0
    if place.get("data_stale") or place.get("freshness") == "stale":
        score *= 0.8  # stale data lowers confidence
    if not place.get("hours"):
        score *= 0.85  # can't confirm it's open
    return round(max(0.0, min(1.0, score)), 2)
