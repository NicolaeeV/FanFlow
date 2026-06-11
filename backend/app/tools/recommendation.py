"""Shared recommendation schema — every recommendation uses this exact shape, so the UI
and tests never special-case. Nothing is asserted beyond evidence; allergies surface as
food_safety_note + risk_flags; verification status is always present.
"""
from __future__ import annotations
from .place_truth import place_status, claimable_attributes
from .evidence import build_evidence, overall_confidence
from .review_understanding import analyze_reviews
from .hours import hours_for_day
from .i18n import localize, localize_list
from .claim_validator import validate_claim, claim_for_phrase
from .open_hours import assess_open_hours
from .capacity import estimate_capacity
from .soccer_relevance import soccer_relevance
from .transit_connector import get_route
from .route_planner import assess_route
from . import neighborhoods as _nb
from .special_hours import place_special_on


def build_recommendation(rec_type: str, row: dict, place: dict, food_check: dict,
                         constraints: dict, requested_time: dict | None = None,
                         open_status: str | None = None, lang: str = "en",
                         event: dict | None = None, stage: str | None = None,
                         travel_mode: str | None = None,
                         minutes_before_kickoff: int | None = None) -> dict:
    st = place_status(place)
    claim = claimable_attributes(place)
    rev = analyze_reviews(place.get("_id", ""))
    food_status = (food_check or {}).get("status", "ok")
    conf = overall_confidence(place, row.get("rating_confidence", 0), food_status, rev)

    nb = place.get("neighborhood_id", "")
    dist = row.get("distance_km")
    # vicinity-aware route note: distance + which area + how you get there + stage realism,
    # straight from the neighborhood model (local-guide reasoning, one source of truth).
    # Built directly in the visitor's language (already localized — not re-run through localize).
    vicinity = _nb.vicinity_label(nb, stage, lang)
    if isinstance(dist, (int, float)):
        base = {"en": f"~{dist}km from Levi's", "es": f"a ~{dist}km de Levi's",
                "pt": f"a ~{dist}km do Levi's"}.get(lang, f"~{dist}km from Levi's")
    else:
        base = {"en": "near the venue area", "es": "cerca del estadio",
                "pt": "perto do estádio"}.get(lang, "near the venue area")
    route_note = base + (f" · {vicinity}" if vicinity else "")

    # open-at-requested-time handling (never assert open/closed without data)
    open_note, vstatus_override = None, None
    if requested_time and requested_time.get("has_time"):
        wd = requested_time["weekday"]
        hrs = hours_for_day(place, wd)
        if open_status == "open" and hrs:
            open_note = f"open {requested_time.get('label')} ({hrs})"
        elif open_status == "unknown" or not hrs:
            vstatus_override = "needs_verification"
            open_note = f"hours for that time not on file — confirm it's open at {requested_time.get('label')}"
    # official per-place SpecialDay: this spot lists special hours that day (holiday/event) →
    # the regular hours may not hold; flag it (we don't fabricate the special hours)
    special_today = place_special_on(place, event, requested_time) if event else False
    if special_today:
        note = "this spot lists special hours that day — confirm before you go"
        open_note = f"{open_note}; {note}" if open_note else note

    # ---- claim gating: every claim must be backed by the source policy ----
    review_cues = list((rev.get("cues") or {}).keys())
    ctx = {"review_cues": review_cues, "bayesian_rating": row.get("bayesian_rating", 0),
           "is_hidden_gem": row.get("is_hidden_gem"), "local_signal": claim["local_favorite"],
           "confidence": conf}

    # why_it_fits — drop any phrase whose underlying claim the source can't back
    why, claims_dropped = [], []
    for ph in row.get("why", []):
        ct = claim_for_phrase(ph)
        if ct is None:
            why.append(ph)
            continue
        v = validate_claim(ct, place, ctx)
        if v["allowed"]:
            why.append(ph)
        else:
            claims_dropped.append({"phrase": ph, "claim": ct, "reason": v["reason"]})

    # validated claim summary for the card (compact)
    to_check = []
    if claim["local_favorite"] or "local_favorite" in review_cues:
        to_check.append("local_favorite")
    if row.get("is_hidden_gem"):
        to_check.append("hidden_gem")
    if requested_time and requested_time.get("has_time"):
        to_check.append("open_now")
    if (constraints or {}).get("has_constraints"):
        to_check.append("menu")
    validated_claims, call_ahead = [], False
    for ct in to_check:
        v = validate_claim(ct, place, ctx)
        validated_claims.append({"claim": ct, "label": v["label"], "note": v["user_facing_note"]})
        if ct in ("open_now", "menu") and v["label"] == "needs_verification":
            call_ahead = True
    if (constraints or {}).get("allergies") or ((food_check or {}).get("requires_verification")):
        call_ahead = True
    # food safety note
    food_note = None
    if (constraints or {}).get("has_constraints"):
        notes = (food_check or {}).get("notes", [])
        food_note = ("; ".join(notes) or "no specific allergen info — call ahead")
        if (food_check or {}).get("requires_verification"):
            food_note += " · verify directly before relying on it"

    # tradeoffs
    tradeoffs = []
    if row.get("is_hidden_gem"):
        tradeoffs.append("fewer reviews than a tourist magnet, but stronger local signal")
    if claim["is_chain"]:
        tradeoffs.append("convenient but less local")
    if not tradeoffs:
        tradeoffs.append("well-rated and reliable")

    # risk flags (honest) — merge place-truth flags + recommendation-level flags
    risk = list(st.get("risk_flags", []))
    if (row.get("reviews") or 0) < 200:
        risk.append("few_reviews")
    if st["verification_status"] != "verified":
        risk.append(f"place_{st['verification_status']}")
    if food_status == "warn":
        risk.append("food_info_unverified")
    if (food_check or {}).get("requires_verification") and (constraints or {}).get("allergies"):
        risk.append("allergen_cross_contact_unknown")
    if rev.get("injection_filtered"):
        risk.append("review_instructions_ignored")
    # route feasibility: a far place is a weaker match-day choice
    if isinstance(row.get("distance_km"), (int, float)) and row["distance_km"] > 20:
        risk.append("far_from_route")
    if vstatus_override:
        risk.append("hours_unknown_for_time")

    # ---- match-day usefulness: open-hours viability, crowd risk, soccer relevance ----
    oh = place.get("_oh") or (assess_open_hours(place, event, requested_time) if event else None)
    cap = estimate_capacity(place, event, requested_time) if event else None
    soc = soccer_relevance(place)
    route = get_route(place, event or {}, requested_time)
    rte = assess_route(place, event or {}, requested_time, stage, travel_mode, minutes_before_kickoff)
    if oh and oh.get("call_ahead_required"):
        call_ahead = True
    if special_today:
        call_ahead = True   # a listed special day overrides regular hours — always confirm
    if oh and oh.get("open_now_status") == "needs_verification":
        risk.append("open_status_unverified")
    if cap and cap.get("crowd_risk") == "high":
        risk.append("crowd_high")
    risk = sorted(set(risk))

    # local-economy reason (reputation -> candidate, never a verified fact; chains get none)
    tags = set(place.get("local_tags", []))
    local_economy_reason = None
    if not claim["is_chain"]:
        if "family_owned" in tags:
            local_economy_reason = "family-owned local business"
        elif "local_favorite" in tags:
            local_economy_reason = "neighborhood favorite (candidate)"
        elif "cultural" in tags:
            local_economy_reason = "cultural-corridor local spot"
        elif "hidden" in tags:
            local_economy_reason = "under-the-radar local spot (candidate)"
        else:
            local_economy_reason = "independent local business"

    verification = vstatus_override or st["verification_status"]
    if vstatus_override:
        conf = round(conf * 0.85, 2)  # can't confirm open at the asked time -> lower confidence

    return {
        "place_id": place.get("_id"),
        "name": place.get("name"),
        "recommendation_type": rec_type,
        "verification_status": verification,
        "confidence": conf,
        "why_it_fits": localize_list(why, lang),
        "tradeoffs": localize_list(tradeoffs, lang),
        "route_note": route_note,   # already built in the visitor's language
        "food_safety_note": localize(food_note, lang) if food_note else None,
        "open_status_note": localize(open_note, lang) if open_note else None,
        "special_hours_today": special_today,
        "evidence": build_evidence(place, rev),
        "risk_flags": risk,
        "claims": validated_claims,
        "claims_dropped": claims_dropped,
        "call_ahead": call_ahead,
        "open_hours": ({k: oh[k] for k in ("open_now_status", "pre_match_viable", "post_match_viable",
                                           "late_night_viable", "hours_source", "freshness",
                                           "call_ahead_required")} if oh else None),
        "local_economy_reason": local_economy_reason,
        "crowd_risk": (cap.get("crowd_risk") if cap else "unknown"),
        "backup_needed": (cap.get("backup_needed") if cap else False),
        "busy_now_percentage": (cap.get("now_percentage") if cap else None),
        "soccer_label": soc["label"],
        "transit_note": route.get("route_note"),
        "transit_risk": route.get("route_risk"),
        "late_night_warning": route.get("late_night_warning"),
        # traffic-aware route tradeoff (every claim is live / estimated / needs_verification)
        "eta_minutes": rte["eta_minutes"],
        "route_mode": rte["route_mode"],
        "traffic_delay_estimate": rte["traffic_delay_estimate"],
        "route_risk": rte["route_risk"],
        "arrival_buffer_before_kickoff": rte["arrival_buffer_before_kickoff"],
        "post_match_exit_risk": rte["post_match_exit_risk"],
        "route_tradeoff_label": rte["route_tradeoff_label"],
        "route_tradeoff_note": localize(rte["route_tradeoff_note"], lang) if rte["route_tradeoff_note"] else None,
        "route_source": rte["source"],
        "route_dist_km": rte["route_dist_km"],
        # display extras (not part of the canonical contract, safe to ignore)
        "bayesian_rating": row.get("bayesian_rating"),
        "reviews": row.get("reviews"),
        "is_hidden_gem": row.get("is_hidden_gem"),
    }
