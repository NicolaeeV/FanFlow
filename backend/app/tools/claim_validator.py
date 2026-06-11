"""Claim validator — the single gate every user-facing claim passes through.

Given a claim type (open_now, hours, rating, menu, allergy_safe, vegan/halal/kosher/
gluten_free, soccer_pub, watch_party, historic, local_favorite, hidden_gem, closed_or_moved,
just_opened, parking, transit_route, visibility_advice) and either a place (we resolve its
backing source) or an explicit source_type, it returns whether the claim may be ASSERTED,
the trust label, the reason, the required source types, the evidence used, and a plain note.

Policy (see SOURCE_TRUST_POLICY.md): no source -> needs_verification; unsupported source ->
not claimed; stale -> downgrade + lower confidence; public/social -> candidate only;
allergy/gluten-safety -> NEVER guaranteed without verification; reputation (local_favorite/
hidden_gem) -> at most 'candidate', never a verified fact.
"""
from __future__ import annotations
from .source_catalog import (SOURCE_CATALOG, CLAIM_RULES, requires_verification, label_evidence,
                             VERIFIED_SOURCE, OFFICIAL_SOURCE, BUSINESS_OWNED_SOURCE,
                             PLATFORM_SOURCE, PUBLIC_POST_CANDIDATE, PROHIBITED_OR_UNUSABLE)

VERIFIED, CANDIDATE, NEEDS_VERIFICATION, PROHIBITED, ADVICE = (
    "verified", "candidate", "needs_verification", "prohibited", "advice")

# validator claim -> source_catalog CLAIM_RULES key
_CATALOG_KEY = {
    "open_now": "open_now", "hours": "hours", "rating": "rating", "review_count": "rating",
    "menu": "menu", "category": "category", "soccer_pub": "soccer_pub",
    "watch_party": "watch_party_event", "watch_party_event": "watch_party_event",
    "historic": "historic", "local_favorite": "local_favorite", "hidden_gem": "hidden_gem",
    "closed_or_moved": "closure_status",
}
ALWAYS_VERIFY = {"allergy_safe", "gluten_free", "celiac"}        # never "guaranteed safe"
DIET_SOFT = {"vegan", "vegetarian", "halal", "kosher", "no_pork"}  # candidate "offers X — confirm"
REPUTATION = {"local_favorite", "hidden_gem"}                    # max label = candidate


def _required(claim: str) -> list:
    key = _CATALOG_KEY.get(claim)
    return sorted(CLAIM_RULES.get(key, {}).get("sufficient", set())) if key else []


def _place_source_for(claim: str, place: dict, context: dict) -> str | None:
    """Which catalog source (if any) on this place can back the claim."""
    food = place.get("food", {}) or {}
    cues = set(context.get("review_cues", []))
    live = bool(place.get("google_place_id"))
    if claim in ("rating", "review_count", "category", "hours", "price", "closed_or_moved"):
        return "places_api" if live else ("seed" if place else None)
    if claim == "open_now":
        return "places_api" if live else None          # seed hours can't assert *live* open
    if claim == "menu":
        if place.get("website") and food.get("info_status") == "menu_published":
            return "business_website"
        if place.get("gbp", {}).get("has_menu_link"):
            return "gbp"
        return None
    if claim in DIET_SOFT:
        opts = set(food.get("diet_options", [])) | set(food.get("religious_options", []))
        if claim in opts:
            return "business_website" if place.get("website") else "seed"
        return None
    if claim in ("soccer_pub", "watch_party", "watch_party_event", "historic", "just_opened"):
        return None                                     # no official/business source on seed
    if claim == "local_favorite":
        if "local_favorite" in cues:
            return "reddit_public_post"                 # candidate via public review cue
        if "local_favorite" in place.get("local_tags", []):
            return "seed"
        return None
    if claim == "hidden_gem":
        return "seed" if place else None                # gated further by bayesian+local below
    if claim in ("parking", "transit_route"):
        return "city_open_data"
    return None


def _result(claim, allowed, label, reason, required, evidence, note):
    return {"claim": claim, "allowed": allowed, "label": label, "reason": reason,
            "required_source_types": required, "evidence_used": evidence, "user_facing_note": note}


def validate_claim(claim_type: str, place: dict | None = None, context: dict | None = None,
                   source_type: str | None = None) -> dict:
    context = context or {}
    required = _required(claim_type)
    src = source_type or _place_source_for(claim_type, place or {}, context)
    freshness = context.get("freshness") or (place or {}).get("data_freshness") or "unknown"
    if place and place.get("google_place_id") and claim_type in ("open_now", "rating", "hours", "category"):
        freshness = "live"

    # 1) safety claims can NEVER be asserted without verification
    if claim_type in ALWAYS_VERIFY:
        return _result(claim_type, False, NEEDS_VERIFICATION,
                       "allergen/gluten safety can never be guaranteed without verified menu data",
                       _required("allergy_safe"), None,
                       "Call ahead — we can't guarantee allergen safety.")

    # 2) visibility advice is guidance, not a place fact or a ranking promise
    if claim_type == "visibility_advice":
        return _result(claim_type, True, ADVICE,
                       "owner guidance to improve readiness/relevance/conversion (no organic-rank promise)",
                       [], {"source": "policy", "freshness": "n/a"},
                       "Improves readiness & conversion — organic Google rank can't be bought or guaranteed.")

    # 3) no backing source -> needs verification
    if not src:
        return _result(claim_type, False, NEEDS_VERIFICATION,
                       f"no source on file can back '{claim_type}'", required, None,
                       "Needs verification.")

    s = SOURCE_CATALOG.get(src)
    if not s:
        return _result(claim_type, False, NEEDS_VERIFICATION, f"unknown source '{src}'", required, None,
                       "Needs verification.")
    if s["trust"] == PROHIBITED_OR_UNUSABLE:
        return _result(claim_type, False, PROHIBITED, "source is prohibited/unusable per ToS",
                       required, None, "Source not usable.")

    ev = label_evidence(src, freshness, context.get("confidence", 0.6))
    evidence = {"source": src, "trust": s["trust"], "freshness": freshness,
                "confidence": ev["confidence"], "attribution": s.get("attribution")}

    # 4) hidden gem needs Bayesian rating + a local signal
    if claim_type == "hidden_gem":
        ok = (context.get("bayesian_rating", 0) >= 4.3 and
              bool(context.get("local_signal") or context.get("is_hidden_gem")))
        if not ok:
            return _result(claim_type, False, NEEDS_VERIFICATION,
                           "hidden-gem needs Bayesian rating >=4.3 AND a local/candidate signal",
                           required, evidence, "Not enough signal to call it a hidden gem.")
        return _result(claim_type, True, CANDIDATE,
                       "Bayesian rating + local signal present", required, evidence,
                       "Local hidden gem (candidate — strong rating + local mentions).")

    # 4b) reputation is inherently a CANDIDATE signal (seed tag or public review cue) —
    #     it is allowed to be shown, but never as an independently 'verified fact'.
    if claim_type == "local_favorite":
        return _result(claim_type, True, CANDIDATE,
                       f"local-favorite signal from {src}", required, evidence,
                       "Locals mention it (candidate — not an independently verified fact).")

    # 5) does the source support this claim at all?
    key = _CATALOG_KEY.get(claim_type, claim_type)
    if requires_verification(src, key):
        return _result(claim_type, False, NEEDS_VERIFICATION,
                       f"{src} does not sufficiently support '{claim_type}'", required, evidence,
                       "Needs verification.")

    # 6) supported -> assign label by trust tier + claim kind
    trust = s["trust"]
    if claim_type in REPUTATION:
        label = CANDIDATE                                # reputation is never a 'verified fact'
        note = "Locals mention it (candidate — not an independently verified fact)."
    elif claim_type in DIET_SOFT:
        label = CANDIDATE
        note = f"May offer {claim_type.replace('_', ' ')} — confirm with the business."
    elif trust in (VERIFIED_SOURCE, OFFICIAL_SOURCE, BUSINESS_OWNED_SOURCE):
        label = VERIFIED
        note = ""
    elif trust == PLATFORM_SOURCE:
        label = VERIFIED if claim_type in ("rating", "hours", "open_now", "category", "review_count") else CANDIDATE
        note = ""
    elif trust == PUBLIC_POST_CANDIDATE:
        label = CANDIDATE
        note = "Candidate signal from public posts — unverified."
    else:
        label = NEEDS_VERIFICATION
        note = "Needs verification."

    # 7) stale data downgrades a verified claim + warns
    if freshness == "stale":
        if label == VERIFIED:
            label = NEEDS_VERIFICATION
        note = (note + " May be out of date — verify.").strip()

    allowed = label in (VERIFIED, CANDIDATE, ADVICE)
    return _result(claim_type, allowed, label,
                   f"supported by {src} ({trust})", required, evidence, note)


# phrase -> claim type, for gating the why-it-fits strings the scorer emits
def claim_for_phrase(phrase: str) -> str | None:
    p = (phrase or "").lower()
    if "historic" in p:
        return "historic"
    if "favorite" in p or "favorito" in p or "favorito" in p or "favorita" in p:
        return "local_favorite"
    if "cultural" in p:
        return "local_favorite"
    if "★" in phrase or "reviews" in p or "reseñas" in p or "avaliações" in p:
        return "rating"
    return None  # descriptive/low-risk (language, route, open-late) — not a gated fact
