"""Hidden-Gem Score — find the places locals love but tourists miss.

Key idea: don't let "most reviews wins". Use a BAYESIAN rating (shrink a place's raw
rating toward the category/area mean by its review count), so a 5.0★ with 12 reviews is
treated as more uncertain than a 4.6★ with 800. Then add local authenticity, route fit,
open-now, comfort match, and a chain penalty — each with a confidence label.

NOTE: this is FanFlow's OWN confidence-adjusted estimate, NOT a model of Google's displayed
star score (Google removed Bayesian averaging in Feb 2017 — its shown rating is now a plain
arithmetic mean). We use shrinkage only to rank fairly inside our own hidden-gem surfacing.
"""
from __future__ import annotations
import math
from ._geo import haversine_km
from .classify import classify_business
from .review_understanding import analyze_reviews

PRIOR_MEAN = 4.2      # global area mean — measured: plain mean across the 9,827 rated Atlas docs = 4.200
PRIOR_WEIGHT = 30     # pseudo-reviews the prior is worth. Real review-count p50=74, p25=10; 30 trusts
                      # a place halfway to its own rating by ~30 reviews — strong enough to tame a thin
                      # 5.0★, light enough to let a genuinely-loved 34-review local surface as a gem.

# Per-category area means (plain mean rating per Google category, measured from the live dataset; only
# categories with >=20 rated docs and a meaningful deviation from 4.2 are listed). Using the RIGHT
# baseline stops the global prior from flattering a weak fast-food chain (which a 4.2 prior pulls 3.7
# UP toward 4.2) and from over-shrinking a strong local in a high-mean cuisine.
CATEGORY_PRIOR_MEAN = {
    "fast_food_restaurant": 3.8, "sandwich_shop": 3.9, "chinese_restaurant": 4.1,
    "coffee_shop": 4.15, "pizza_restaurant": 4.2, "cafe": 4.2, "vietnamese_restaurant": 4.25,
    "korean_restaurant": 4.3, "mexican_restaurant": 4.3, "bakery": 4.3,
    "japanese_restaurant": 4.35, "italian_restaurant": 4.4,
}


def category_prior_mean(category: str | None) -> float:
    """Area mean rating for a category, falling back to the measured global mean (4.2)."""
    return CATEGORY_PRIOR_MEAN.get((category or "").lower(), PRIOR_MEAN)


def bayesian_rating(rating: float | None, reviews: int | None,
                    prior_mean: float = PRIOR_MEAN, prior_weight: int = PRIOR_WEIGHT) -> float:
    r = rating if rating is not None else prior_mean
    n = reviews or 0
    return (prior_weight * prior_mean + n * r) / (prior_weight + n)


def _clamp(x):
    return max(0.0, min(1.0, x))


def hidden_gem_score(biz: dict, event: dict | None = None, demand_langs: set | None = None,
                     intent_cats: list | None = None) -> dict:
    event = event or {}
    demand_langs = demand_langs or set()
    cls = classify_business(biz)
    rating, reviews = biz.get("rating"), biz.get("reviews") or 0
    bayes = bayesian_rating(rating, reviews, prior_mean=category_prior_mean(biz.get("category")))
    # confidence in the rating grows with review volume (Bayesian shrinkage certainty)
    rating_conf = round(reviews / (reviews + PRIOR_WEIGHT), 2)

    dist = haversine_km(biz.get("lat"), biz.get("lon"), event.get("venue_lat"), event.get("venue_lon")) if event else 6.0
    langs = set(biz.get("languages_supported", ["en"]))
    cat = biz.get("category", "")
    secs = set(biz.get("secondary_categories", []))
    comfort = 1.0 if (not intent_cats or cat in intent_cats or secs & set(intent_cats)) else 0.4

    # local sentiment from public review/post snippets (reputation, not review count)
    rev = analyze_reviews(biz.get("_id", ""))
    sentiment = rev.get("local_sentiment", 0.5)

    quality = _clamp((bayes - 3.0) / 2.0)            # 3.0..5.0 -> 0..1
    # LOCALITY AS A POSITIVE: an independent earns a community-locality boost; a chain keeps a base
    # authenticity and takes a SMALL, fixed derank (0.18) — gentle enough that a genuinely good chain
    # (e.g. the single local Yard House, 4.4★) still out-authenticates a mediocre local, but a
    # cherished independent clearly leads. No more 0.6 cliff that floored EVERY chain — good or bad —
    # to authenticity 0, making a great chain indistinguishable from a weak one on this axis.
    is_chn = cls["is_chain"]
    locality_boost = 0.0 if is_chn else (0.30 + (0.20 if cls["is_local_favorite"] else 0.0)
                                         + (0.15 if cls["is_historic_cultural"] else 0.0))
    authenticity = _clamp(0.35 + locality_boost - (0.18 if is_chn else 0.0))
    route_fit = _clamp(1.2 / (1 + dist / 4))
    open_now = 1.0 if cls["late_night_capable"] else 0.7
    lang_clarity = 1.0 if ((langs & demand_langs) - {"en"}) or not demand_langs else 0.6
    # "hidden" bonus: well-rated + locally loved but UNDER-reviewed vs a tourist magnet
    under_reviewed = _clamp((1500 - reviews) / 1500) if reviews else 0.5
    hidden_bonus = 0.6 * quality * under_reviewed * sentiment if cls["is_local_favorite"] else 0.0

    # COMMUNITY-LOCALITY — "how the community cherishes & interacts with this place", from real fields.
    # independence (a verifiable fact, not a reputation claim) dominates; over_loved is the rating
    # ABOVE the place's OWN category norm (loved relative to its peers, not just absolutely high);
    # plus snippet sentiment, local-love cues, and the under-reviewed-yet-beloved (hidden-gem) idea.
    # A GOOD chain is NOT zeroed — it loses the independence + hidden terms but keeps over_loved +
    # sentiment, so a strong chain still scores above a weak one.
    _cat_mean = category_prior_mean(cat)
    _love_cues = {"local_favorite", "hidden_gem", "family_friendly", "authentic"} & set(rev.get("cues") or {})
    over_loved = _clamp(((rating or _cat_mean) - _cat_mean) / 0.6)
    hidden_loved = (_clamp((600 - reviews) / 600) * over_loved) if reviews else over_loved
    community_locality = _clamp(
        0.35 * (0.0 if is_chn else 1.0) + 0.20 * over_loved + 0.20 * sentiment
        + 0.10 * _clamp(len(_love_cues) / 2) + 0.15 * hidden_loved)

    parts = {
        "bayesian_quality": round(quality, 2),
        "authenticity": round(authenticity, 2),
        "community_locality": round(community_locality, 2),
        "local_sentiment": round(sentiment, 2),
        "route_fit": round(route_fit, 2),
        "open_now": round(open_now, 2),
        "comfort_match": round(comfort, 2),
        "language_clarity": round(lang_clarity, 2),
        "hidden_bonus": round(hidden_bonus, 2),
    }
    score = round(100 * _clamp(
        0.26 * quality + 0.10 * authenticity + 0.10 * community_locality + 0.12 * sentiment
        + 0.12 * route_fit + 0.08 * open_now + 0.10 * comfort + 0.06 * lang_clarity + 0.16 * hidden_bonus
    ), 1)

    return {
        "business_id": biz.get("_id"), "name": biz.get("name"),
        "hidden_gem_score": score,
        "bayesian_rating": round(bayes, 2), "raw_rating": rating, "reviews": reviews,
        "rating_confidence": rating_conf,
        "components": parts, "classification_labels": cls["labels"],
        "local_sentiment_confidence": rev.get("confidence", "low"),
        "review_cues": list((rev.get("cues") or {}).keys()),
        "distance_km": round(dist, 1),
        "is_hidden_gem": bool(cls["is_local_favorite"] and reviews < 1200 and bayes >= 4.3 and sentiment >= 0.55),
    }
