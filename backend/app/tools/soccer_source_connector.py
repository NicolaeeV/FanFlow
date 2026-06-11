"""Soccer-source connector — gather soccer-relevance evidence from ALLOWED sources only.

Order of trust: official event/watch-party pages > business website > permitted public posts
> Google Places types/reviews (candidate signal only). Returns evidence with source URL +
confidence. NEVER claims "classic/historic soccer pub" or "home of the fans" without a source.
Seeded for the MVP (fan_venues + review cues); live website/official checks are stubbed hooks.
"""
from __future__ import annotations
from .. import mongo
from .soccer_relevance import soccer_relevance


def _official_watch_party(place_id: str, event_id: str) -> dict | None:
    """Hook: official event / host-city / fan-zone page check. Seeded via fan_venues."""
    fv = next((v for v in mongo.get_fan_venues()
               if v["_id"] == place_id or v.get("business_id") == place_id), None)
    if fv:
        return {"shows_games": True, "watch_party": fv.get("type") in ("watch_party", "soccer_pub"),
                "source": fv.get("source"), "source_type": "official_event",
                "confidence": fv.get("confidence", "medium"),
                "status": "candidate" if fv.get("candidate") else "confirmed"}
    return None


def _business_website_says_soccer(place: dict) -> dict | None:
    """Hook: parse the business's OWN site for 'shows the game / World Cup'. Stub for MVP.

    A real impl fetches place['website'] and looks for soccer/screens language with the URL
    as evidence. Returns None here unless seed marks it (no fabrication)."""
    if (place.get("food") or {}).get("info_status") == "menu_published" and place.get("website"):
        # we have a verified business site but no parsed soccer claim -> no claim
        return None
    return None


def collect_soccer_evidence(place: dict, event: dict | None = None) -> dict:
    pid = place.get("_id", "")
    eid = (event or {}).get("_id", "")
    evidence, sources = [], []

    official = _official_watch_party(pid, eid)
    if official:
        evidence.append(official); sources.append("official_event")

    site = _business_website_says_soccer(place)
    if site:
        evidence.append(site); sources.append("business_website")

    # Places types/reviews + our soccer_relevance layer (candidate signals)
    rel = soccer_relevance(place)
    if rel["label"] != "not_soccer_specific":
        evidence.append({"label": rel["label"], "source_type": rel["source"],
                         "via": "review/category candidate signal"})

    # label: official/business -> can verify; else candidate/general/none
    if official and official.get("status") == "confirmed":
        label = "verified_soccer_hub"
    elif official or site:
        label = "candidate_soccer_spot"
    else:
        label = rel["label"]

    return {
        "business_id": pid, "label": label,
        "can_assert_soccer": bool(official or site),   # only official/business may assert
        "evidence": evidence, "sources": sorted(set(sources)) or [rel["source"]] if rel["source"] else [],
        "user_facing_note": rel["user_facing_note"] if label == rel["label"] else
            "Soccer/watch-party indicated by an official/business source — confirm screenings.",
        "disclaimer": "Never described as a 'classic/historic soccer pub' without a source.",
    }
