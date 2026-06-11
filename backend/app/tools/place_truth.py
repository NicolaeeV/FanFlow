"""Place truth — the single source of "can we recommend this, and what may we claim?".

Returns a verification status (verified | candidate | needs_verification | closed) and a
recommendability flag. NOTHING about a place may be asserted beyond what the underlying
record supports — no invented history, soccer reputation, "locals love it", or open/closed
status. Closed places are never recommendable.
"""
from __future__ import annotations

STATUSES = {"verified", "candidate", "needs_verification", "closed"}


def place_status(place: dict) -> dict:
    if not place:
        return {"verification_status": "needs_verification", "is_recommendable": False,
                "reasons": ["no record"], "risk_flags": ["no_record"]}
    if str(place.get("business_status", "")).lower() in (
            "closed", "closed_temporarily", "closed_permanently"):
        return {"verification_status": "closed", "is_recommendable": False,
                "reasons": ["permanently/temporarily closed"], "risk_flags": ["closed"]}

    vs = place.get("verification_status")
    if vs not in STATUSES or vs == "closed":
        vs = "needs_verification"

    risk, reasons = [], []
    # missing hours => we can't claim it's open => downgrade
    if not place.get("hours"):
        vs = "needs_verification"
        risk.append("hours_unknown")
        reasons.append("hours not on file — confirm it's open")
    # explicitly flagged stale data lowers trust
    if place.get("data_stale") or place.get("freshness") == "stale":
        risk.append("stale_data")
        reasons.append("data may be out of date")
    # missing allergen/menu data => menu uncertainty
    if not (place.get("food") or {}).get("info_status") or \
       (place.get("food") or {}).get("info_status") == "unknown":
        risk.append("menu_allergen_unverified")

    return {"verification_status": vs, "is_recommendable": True,
            "reasons": reasons, "risk_flags": risk}


def claimable_attributes(place: dict) -> dict:
    """What we are allowed to STATE about a place (only what the record supports)."""
    tags = set(place.get("local_tags", []))
    return {
        "is_chain": bool(place.get("chain")),
        "local_favorite": "local_favorite" in tags,      # only if tagged in data
        "historic": "historic" in tags,                  # never claim history otherwise
        "family_owned": "family_owned" in tags,
        "cultural": "cultural" in tags,
        "has_rating": place.get("rating") is not None,
        # soccer reputation is NOT claimable from a generic business record:
        "soccer_reputation": False,
    }
