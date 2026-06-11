"""Local Favorites classifier.

Turns raw Places-style business data into the labels the discovery engine reasons
over: local-favorite vs chain, historic/cultural, family/group-friendly, late-night
capable, language readiness, and tourist-conversion readiness. Heuristic + explainable;
calibrate with real review-text / GBP data in production.
"""
from __future__ import annotations
from ._geo import latest_close_hour

FAMILY_GROUP_CATS = {
    "mexican_restaurant", "italian_restaurant", "american_restaurant",
    "vietnamese_restaurant", "pizza_restaurant",
}


def classify_business(biz: dict) -> dict:
    rating = biz.get("rating") or 0
    reviews = biz.get("reviews") or 0
    tags = set(biz.get("local_tags", []))
    chain = bool(biz.get("chain"))
    langs = set(biz.get("languages_supported", ["en"]))
    gbp = biz.get("gbp", {})
    close_h = latest_close_hour(biz)

    is_local_favorite = (not chain) and (
        "local_favorite" in tags or "historic" in tags or (rating >= 4.4 and reviews >= 300)
    )
    is_historic_cultural = bool(tags & {"historic", "cultural"})
    family_group = (biz.get("category") in FAMILY_GROUP_CATS) or ("family_owned" in tags)
    late_night = close_h is not None and close_h >= 22  # closes 22:00 or later (incl. after-midnight)

    language_readiness = "multilingual" if (langs - {"en"}) else "english_only"

    # conversion readiness: how easy is it for a tourist to act?
    conv = 0
    if gbp.get("has_menu_link"): conv += 1
    if gbp.get("has_reservation_link"): conv += 1
    if biz.get("website"): conv += 1
    if (gbp.get("photos", biz.get("photos", 0)) or 0) >= 10: conv += 1
    conversion_readiness = ["weak", "weak", "fair", "good", "strong"][min(conv, 4)]

    labels = []
    if is_local_favorite: labels.append("local_favorite")
    if chain: labels.append("chain")
    if is_historic_cultural: labels.append("historic_cultural")
    if family_group: labels.append("family_group_friendly")
    if late_night: labels.append("late_night_capable")
    if language_readiness == "multilingual": labels.append("multilingual")

    return {
        "is_local_favorite": is_local_favorite,
        "is_chain": chain,
        "is_historic_cultural": is_historic_cultural,
        "family_group_friendly": family_group,
        "late_night_capable": late_night,
        "language_readiness": language_readiness,
        "conversion_readiness": conversion_readiness,
        "latest_close_hour": None if close_h is None else (close_h - 24 if close_h >= 24 else close_h),
        "labels": labels,
    }
