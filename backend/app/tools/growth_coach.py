"""Google Growth Coach — help a local business get FOUND and CHOSEN on Google during the
matchday demand surge.

This is FanFlow's second engine: the Demand engine answers "how many fans are coming and
when"; the Growth engine answers "how does THIS business get found and chosen on Google Search,
Maps, Business Profile, and Ads during that surge."

Grounded in Google's stated local-ranking framework (verified against support.google.com):
  • Local results are ranked by RELEVANCE, DISTANCE, PROMINENCE.
  • Organic local rank CANNOT be bought or guaranteed.
  • Google Ads Quality Score is a 1–10 DIAGNOSTIC (expected CTR, ad relevance, landing-page
    experience), NOT a direct auction input.
So we never promise rank #1. We score the KNOWN, CONTROLLABLE inputs, split them from
structural factors the owner can't change, and hand over concrete fixes + ready-to-use copy.

PRIVACY: every signal is aggregate (geo / language / match-timing / intent). Language variants
are gated by AGGREGATE language demand, never by a visitor's identity, nationality, or
ethnicity. The Review Assistant never fabricates reviews — it only helps respond to real ones
and request honest ones.
"""
from __future__ import annotations
from .. import mongo
from ._geo import haversine_km, open_during_window, closes_before
from .business_tags import infer_business_tags
from ..guardrails import scrub_text

import math

# ── business "kind" → category-specific playbook ─────────────────────────────
KIND_RULES = [
    ("bar", ("bar", "sports_bar", "pub", "night_club", "brewery", "wine_bar")),
    ("cafe", ("cafe", "coffee_shop")),
    ("bakery", ("bakery",)),
    ("deli", ("sandwich_shop", "deli", "delicatessen")),
    ("market", ("grocery_store", "supermarket", "convenience_store", "liquor_store",
                "food_store", "asian_grocery_store", "market")),
    ("parking", ("parking", "parking_lot")),
    ("hotel", ("lodging", "hotel", "motel")),
    ("gas", ("gas_station",)),
    ("retail", ("shopping_mall", "clothing_store", "store", "department_store", "gift_shop")),
]


def business_kind(biz: dict) -> str:
    cat = (biz.get("category") or "").lower()
    secs = {str(s).lower() for s in biz.get("secondary_categories", [])}
    for kind, cats in KIND_RULES:
        if cat in cats or (secs & set(cats)):
            # restaurants shouldn't be miscaught by a generic "store" secondary
            return kind
    if "restaurant" in cat or cat in ("taqueria", "meal_takeaway", "meal_delivery", "food"):
        return "restaurant"
    tags = set(infer_business_tags(biz, use_reviews=False)["tags"])
    if tags & {"bar", "watch_party"}:
        return "bar"
    if tags & {"coffee", "cafe"}:
        return "cafe"
    if tags & {"deli", "sandwiches"}:
        return "deli"
    if tags & {"local_market", "groceries"}:
        return "market"
    if tags & {"tacos", "mexican", "italian", "pizza", "vietnamese", "restaurant", "prepared_food"}:
        return "restaurant"
    return "generic"


# Per-kind copy + the levers that matter. {venue}/{nb}/{home}/{away} are filled per match.
PLAYBOOK = {
    "restaurant": {
        "conversion": "reservation/order link",
        "attributes": ["dine_in", "takeout", "good_for_groups", "serves_vegetarian"],
        "post_angles": ["Open late for {home} vs {away}", "Group tables for the match",
                        "Fast service before kickoff", "Easy stop on the way to {venue}"],
        "headlines": ["Open Late Near {venue}", "Dinner Before the Match", "Group Tables for Fans",
                      "Reserve Now for Matchday", "Fast Service Near {venue}"],
        "descriptions": ["Make matchday easy — fast service, group seating, and quick directions from {nb}.",
                         "Eat before or after {home} vs {away}. Reserve a table or order ahead."],
    },
    "bar": {
        "conversion": "reservation / 'reserve a table' link",
        "attributes": ["good_for_groups", "serves_beer", "live_sports", "dine_in"],
        "post_angles": ["Watch {home} vs {away} on the big screens", "Every match shown live",
                        "Late hours on matchday", "Group bookings for the game"],
        "headlines": ["Watch the Match Live", "Every Goal on the Big Screen", "Matchday Bar Near {venue}",
                      "Reserve Your Table for {home}", "Open Late for the Game"],
        "descriptions": ["Watch {home} vs {away} live with cold drinks and the best crowd near {nb}.",
                         "Big screens, late hours, group tables. Reserve ahead for matchday."],
    },
    "cafe": {
        "conversion": "mobile order link",
        "attributes": ["takeout", "serves_vegetarian", "good_for_groups"],
        "post_angles": ["Early open on matchday", "Coffee before kickoff", "Grab-and-go for the walk to {venue}"],
        "headlines": ["Coffee Before Kickoff", "Open Early Near {venue}", "Grab-and-Go for the Match",
                      "Order Ahead, Skip the Line"],
        "descriptions": ["Fuel up before {home} vs {away} — fast espresso and grab-and-go near {nb}.",
                         "Open early on matchday. Order ahead and skip the line."],
    },
    "bakery": {
        "conversion": "order-ahead link",
        "attributes": ["takeout", "serves_vegetarian"],
        "post_angles": ["Fresh for matchday morning", "Grab-and-go pastries before the game"],
        "headlines": ["Fresh Pastries Near {venue}", "Grab-and-Go Before the Match", "Open Early on Matchday"],
        "descriptions": ["Fresh-baked and ready before {home} vs {away}. Quick stop near {nb}.",
                         "Order ahead for matchday morning — pastries, coffee, grab-and-go."],
    },
    "deli": {
        "conversion": "online order / 'order sandwiches' link",
        "attributes": ["takeout", "good_for_groups", "serves_vegetarian"],
        "post_angles": ["Sandwiches & grab-and-go for matchday", "Order a group platter for the game",
                        "Quick lunch before kickoff"],
        "headlines": ["Sandwiches Near {venue}", "Grab-and-Go for the Match", "Group Platters for Fans",
                      "Quick Lunch Before Kickoff"],
        "descriptions": ["Fresh sandwiches and prepared food before {home} vs {away}. Order ahead from {nb}.",
                         "Group platters and grab-and-go for matchday. Quick stop near the stadium."],
    },
    "market": {
        "conversion": "directions + 'in-store' info",
        "attributes": ["takeout"],
        "post_angles": ["Water, ice & snacks for matchday", "Stock up before the walk to {venue}",
                        "Grab-and-go for the game"],
        "headlines": ["Water, Ice & Snacks Near {venue}", "Stock Up Before the Match",
                      "Grab-and-Go for Matchday", "Open Late on Game Day"],
        "descriptions": ["Water, snacks, ice and grab-and-go before {home} vs {away}. Quick stop in {nb}.",
                         "Everything for the walk to the stadium — open late on matchday."],
    },
    "parking": {
        "conversion": "prepay / reservation link",
        "attributes": [],
        "post_angles": ["Reserve matchday parking near {venue}", "Prepay and skip the line",
                        "Easy in/out for the game"],
        "headlines": ["Parking Near {venue}", "Prepay Matchday Parking", "Reserve Your Spot for {home}",
                      "Easy In & Out for the Game"],
        "descriptions": ["Reserve parking near {venue} for {home} vs {away}. Prepay and skip the line.",
                         "Guaranteed matchday parking with easy exit. Book ahead from {nb}."],
    },
    "hotel": {
        "conversion": "booking link",
        "attributes": ["good_for_groups"],
        "post_angles": ["Matchday stays near {venue}", "Walk or shuttle to the game",
                        "Local matchday guide for guests"],
        "headlines": ["Stay Near {venue}", "Matchday Rooms for Fans", "Walk to the Game",
                      "Book Your Matchday Stay"],
        "descriptions": ["Stay close to {venue} for {home} vs {away}. Shuttle, concierge, local guide.",
                         "Matchday rooms with easy access to the stadium and {nb}."],
    },
    "gas": {
        "conversion": "directions",
        "attributes": ["takeout"],
        "post_angles": ["Fuel, water & snacks before the game", "Last stop before {venue}"],
        "headlines": ["Fuel & Snacks Near {venue}", "Last Stop Before the Match", "Open Late on Game Day"],
        "descriptions": ["Fuel up, grab water and snacks before {home} vs {away}. On the way to {venue}.",
                         "Your last stop before the game — open late on matchday."],
    },
    "retail": {
        "conversion": "directions / shop link",
        "attributes": [],
        "post_angles": ["Jerseys, flags & fan gear for matchday", "Get ready for {home} vs {away}",
                        "Souvenirs and essentials near {venue}"],
        "headlines": ["Fan Gear Near {venue}", "Jerseys, Flags & Souvenirs", "Get Ready for Matchday",
                      "Chargers, Sunscreen & More"],
        "descriptions": ["Jerseys, flags, chargers and matchday essentials near {nb}.",
                         "Gear up for {home} vs {away} — souvenirs and fan essentials by the stadium."],
    },
    "generic": {
        "conversion": "website / contact link",
        "attributes": [],
        "post_angles": ["Open for matchday near {venue}", "Quick stop before {home} vs {away}"],
        "headlines": ["Open for Matchday", "Near {venue}", "Quick Stop Before the Game"],
        "descriptions": ["Make matchday easy near {venue} — quick service and easy directions from {nb}.",
                         "Open for {home} vs {away}. Find us near {nb}."],
    },
}

# multilingual matchday-post bodies, keyed by language. Only emitted when AGGREGATE language
# demand supports the language. Never identity-based.
POST_I18N = {
    "es": "Abierto para {home} vs {away} — servicio rápido, mesas para grupos y a poca distancia de {venue}.",
    "pt": "Aberto para {home} vs {away} — serviço rápido, mesas para grupos e perto de {venue}.",
    "ar": "مفتوحون لمباراة {home} ضد {away} — خدمة سريعة وطاولات للمجموعات وعلى مقربة من {venue}.",
    "fr": "Ouvert pour {home} vs {away} — service rapide, tables pour groupes, à deux pas de {venue}.",
}
# Neutral, sentiment-blind review-request copy — invites EVERY customer to leave an honest
# review (good or bad). Asking only happy customers is "review gating", which Google prohibits
# (support.google.com/business/answer/7400114) and which can block a profile from new reviews.
REVIEW_REQUEST_I18N = {
    "en": "Thanks for visiting! If you have a minute, an honest Google review — good or bad — helps a local business like ours serve fans better during the tournament.",
    "es": "¡Gracias por tu visita! Si tienes un minuto, una reseña honesta en Google —buena o no— ayuda a un negocio local como el nuestro a atender mejor a los aficionados durante el torneo.",
    "pt": "Obrigado pela visita! Se tiver um minuto, uma avaliação honesta no Google — boa ou não — ajuda um negócio local como o nosso a atender melhor os torcedores durante o torneio.",
    "ar": "شكرًا لزيارتك! إذا كان لديك دقيقة، فإن تقييمًا صادقًا على جوجل — إيجابيًا كان أم سلبيًا — يساعد متجرًا محليًا مثلنا على خدمة المشجعين بشكل أفضل خلال البطولة.",
    "fr": "Merci de votre visite ! Si vous avez une minute, un avis Google honnête — positif ou négatif — aide un commerce local comme le nôtre à mieux accueillir les supporters pendant le tournoi.",
}

MATCHDAY_RELEVANT = {
    "mexican_restaurant": 1.0, "taqueria": 1.0, "sports_bar": 1.0, "bar": 0.9,
    "restaurant": 0.85, "fast_food_restaurant": 0.9, "cafe": 0.8, "coffee_shop": 0.8,
    "sandwich_shop": 0.85, "deli": 0.85, "bakery": 0.7, "parking": 1.0, "parking_lot": 1.0,
    "convenience_store": 0.85, "grocery_store": 0.7, "supermarket": 0.7, "liquor_store": 0.7,
    "american_restaurant": 0.8, "italian_restaurant": 0.75, "vietnamese_restaurant": 0.7,
    "lodging": 0.9, "hotel": 0.9, "gas_station": 0.6, "shopping_mall": 0.6,
}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _demand_langs(mix: dict, threshold: float = 0.05) -> list[str]:
    """Languages with AGGREGATE demand share >= threshold (excluding en/other). Operational
    targeting only — never identity."""
    return [l["lang"] for l in mix.get("language_mix", [])
            if l["lang"] not in ("en", "other") and l.get("share", 0) >= threshold]


def _is_google(biz: dict) -> bool:
    return bool(biz.get("google_place_id"))


def _source_label(biz: dict, present: bool) -> str:
    if not present:
        return "unavailable"
    return "google_places" if (biz.get("places_enriched_at") or biz.get("_source") == "places_api") else "seed"


def _component(key, label, value, weight, *, source, fixable, reason, fix, confidence):
    """One readiness component with full provenance. value=None means 'not enough signal' —
    excluded from the score and surfaced under unknowns."""
    return {"key": key, "label": label, "value": (round(value, 2) if value is not None else None),
            "weight": weight, "source": source, "confidence": confidence, "fixable": fixable,
            "reason": reason, "recommended_fix": fix}


# ── 1. Matchday Search Readiness Score ───────────────────────────────────────
def matchday_search_readiness(business_id: str, match_id: str) -> dict:
    """Renamed from 'Google Visibility Score'. Scores the KNOWN controllable + structural inputs
    to Google's relevance/distance/prominence, each with provenance, and renormalizes over the
    components we actually have data for (missing data -> 'not enough signal', never fabricated).
    """
    biz = mongo.get_business(business_id) or {}
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    gbp = biz.get("gbp", {}) or {}
    kind = business_kind(biz)

    website = biz.get("website")
    hours = biz.get("hours")
    photos = gbp.get("photos", biz.get("photos", 0)) or 0
    rating = biz.get("rating")
    reviews = biz.get("reviews")
    has_menu = bool(gbp.get("has_menu_link"))
    has_resv = bool(gbp.get("has_reservation_link"))
    editorial = biz.get("editorial_summary")
    supported = set(biz.get("languages_supported", ["en"]))
    demand = {l["lang"]: l["share"] for l in mix.get("language_mix", [])}
    unmet = [lg for lg in _demand_langs(mix) if lg not in supported]

    # service attributes actually present (from enriched Places data)
    attr_keys = ["dine_in", "takeout", "delivery", "good_for_groups", "serves_beer",
                 "serves_vegetarian", "good_for_children"]
    present_attrs = [a for a in attr_keys if biz.get(a) is not None]
    wanted_attrs = PLAYBOOK[kind]["attributes"]

    comps: list[dict] = []

    # completeness (controllable) — fraction of core profile fields present
    core = {"website": bool(website), "hours": bool(hours), "phone": bool(biz.get("phone")),
            "description": bool(editorial), "photos": photos >= 3}
    completeness = sum(core.values()) / len(core)
    miss = [k for k, v in core.items() if not v]
    comps.append(_component(
        "completeness", "Profile completeness", completeness, 0.13,
        source=_source_label(biz, True), fixable=True, confidence="high" if _is_google(biz) else "low",
        reason=("Missing: " + ", ".join(miss)) if miss else "Core profile fields present",
        fix=("Add " + ", ".join(miss) + " to your Google Business Profile") if miss else "Keep your profile fresh"))

    # category relevance (structural)
    cat_rel = MATCHDAY_RELEVANT.get((biz.get("category") or "").lower(), 0.5)
    comps.append(_component(
        "category_relevance", "Category relevance to matchday search", cat_rel, 0.07,
        source=_source_label(biz, bool(biz.get("category"))), fixable=False, confidence="high",
        reason=f"Your category '{biz.get('category')}' fits common matchday searches at {int(cat_rel*100)}%",
        fix="Confirm your primary category is the most accurate one (a fixable nuance)"))

    # distance to fan flow (structural)
    dist = haversine_km(biz.get("lat"), biz.get("lon"), ev.get("venue_lat"), ev.get("venue_lon"))
    dist_val = _clamp(1.3 / (1 + dist / 4)) if dist is not None else None
    comps.append(_component(
        "distance_to_flow", "Distance to fan flow", dist_val, 0.06,
        source=_source_label(biz, dist is not None), fixable=False, confidence="high",
        reason=f"~{round(dist,1)}km from {ev.get('venue_name','the venue')}" if dist is not None else "Location unknown",
        fix="Structural — can't change location, but matchday Posts/ads can extend your reach"))

    # rating (prominence; semi-controllable via service quality)
    rating_val = _clamp((rating or 0) / 5) if rating is not None else None
    comps.append(_component(
        "rating", "Rating", rating_val, 0.09,
        source=_source_label(biz, rating is not None), fixable=False,
        confidence="high" if rating is not None else "low",
        reason=f"{rating}★ on Google" if rating is not None else "No rating on file",
        fix="Earned over time through service quality and review responses"))

    # review count (prominence)
    rc_val = _clamp(min(math.log10((reviews or 0) + 1) / 3.2, 1)) if reviews is not None else None
    comps.append(_component(
        "review_count", "Review volume", rc_val, 0.08,
        source=_source_label(biz, reviews is not None), fixable=True,
        confidence="high" if reviews is not None else "low",
        reason=f"{reviews} Google reviews" if reviews is not None else "No review count on file",
        fix="Ask EVERY recent customer for an honest review (gating to only happy ones breaks Google policy)"))

    # review recency — real now IF we fetched review text (latest_review_age); else not enough signal
    latest = biz.get("latest_review_age")
    rec_val, rec_src, rec_reason = None, "unavailable", "No dated review text fetched for this place yet"
    if latest:
        low = latest.lower()
        rec_val = (0.3 if ("year" in low) else 0.7 if ("month" in low) else 1.0)  # fresher = higher
        rec_src, rec_reason = "google_places", f"Most recent review: ~{latest}"
    comps.append(_component(
        "review_recency", "Review recency", rec_val, 0.05,
        source=rec_src, fixable=True, confidence="medium" if latest else "low",
        reason=rec_reason,
        fix="Keep a steady trickle of recent reviews (recency signals an active business)"))

    # photo readiness (controllable)
    photo_val = _clamp(min(photos / 12, 1))
    comps.append(_component(
        "photo_readiness", "Photo readiness", photo_val, 0.10,
        source=_source_label(biz, True), fixable=True, confidence="high" if _is_google(biz) else "low",
        reason=f"{photos} photos on your profile",
        fix="Add 10+ recent food/interior/exterior photos" if photos < 10 else "Refresh photos periodically"))

    # conversion links (controllable)
    conv = (0.4 if website else 0) + (0.3 if has_menu else 0) + (0.3 if has_resv else 0)
    conv_missing = [n for n, v in (("website", website), ("menu link", has_menu),
                                   ("reservation/order link", has_resv)) if not v]
    comps.append(_component(
        "conversion_links", "Conversion links", conv, 0.12,
        source=_source_label(biz, True), fixable=True, confidence="high" if _is_google(biz) else "low",
        reason=("Missing: " + ", ".join(conv_missing)) if conv_missing else "Website, menu and booking links present",
        fix=("Add " + ", ".join(conv_missing)) if conv_missing else "Keep links working and current"))

    # matchday hours (controllable)
    hours_val = open_during_window(biz, ev) if hours else None
    early, close_h = closes_before(biz, ev) if hours else (False, None)
    comps.append(_component(
        "matchday_hours", "Matchday / special hours", hours_val, 0.11,
        source=_source_label(biz, bool(hours)), fixable=True,
        confidence="high" if hours else "low",
        reason=("Hours don't cover the full pre+post-match window" if hours and hours_val and hours_val < 1
                else "Hours cover the match window" if hours else "No hours on file"),
        fix=(f"Set special hours — you close ~{close_h}:00 and miss the post-match wave" if early
             else "Publish matchday special hours" if not hours else "Confirm matchday hours")))

    # Google Posts readiness — we can't see Posts via public data (owner-connect required)
    comps.append(_component(
        "posts_readiness", "Google Posts readiness", None, 0.06,
        source="owner_connect_required", fixable=True, confidence="low",
        reason="We can't see your Google Posts from public data — connect your profile to track this",
        fix="Publish a matchday Post (FanFlow generates one below)"))

    # attributes (controllable)
    attr_val = (len([a for a in wanted_attrs if biz.get(a)]) / len(wanted_attrs)) if wanted_attrs else None
    comps.append(_component(
        "attributes", "Business attributes", attr_val, 0.06,
        source=_source_label(biz, bool(present_attrs)), fixable=True,
        confidence="high" if present_attrs else "low",
        reason=(f"{len([a for a in wanted_attrs if biz.get(a)])}/{len(wanted_attrs)} key attributes set"
                if wanted_attrs else "No category-specific attributes tracked"),
        fix="Add attributes like " + ", ".join(a.replace('_', ' ') for a in wanted_attrs) if wanted_attrs
            else "Confirm your profile attributes"))

    # language/content readiness (controllable)
    covered = sum(share for lg, share in demand.items() if lg in supported)
    comps.append(_component(
        "language_content", "Language / content readiness", _clamp(covered), 0.07,
        source=_source_label(biz, True), fixable=True, confidence="medium",
        reason=(f"Aggregate demand includes {', '.join(unmet)} you don't yet cover" if unmet
                else "Your languages cover the aggregate demand"),
        fix=(f"Add {'/'.join(unmet)} menu + profile copy (aggregate language demand, not identity)" if unmet
             else "Keep multilingual copy current")))

    # landing page readiness — only scored when a website exists (else not enough signal)
    if website:
        lp = landing_page_readiness(business_id)
        lp_val = lp.get("score")
        comps.append(_component(
            "landing_page", "Landing-page readiness", (lp_val / 100 if lp_val is not None else None), 0.05,
            source="self_check", fixable=True, confidence="low",
            reason="Ad clicks convert better when the page matches the ad (menu, hours, booking, mobile)",
            fix="Run the landing-page checklist below before spending on ads"))

    # ── score: renormalize over components that HAVE data ──
    known = [c for c in comps if c["value"] is not None]
    wsum = sum(c["weight"] for c in known) or 1.0
    score = round(100 * sum(c["value"] * c["weight"] for c in known) / wsum, 1)
    unknowns = [{"key": c["key"], "label": c["label"], "reason": c["reason"]}
                for c in comps if c["value"] is None]

    controllable = sorted([c for c in comps if c["fixable"] and c["value"] is not None and c["value"] < 0.8],
                          key=lambda c: c["weight"] * (1 - c["value"]), reverse=True)
    structural = [{"factor": c["label"], "value": c["value"], "reason": c["reason"]}
                  for c in comps if not c["fixable"]]

    band = ("Strong" if score >= 75 else "Room to grow" if score >= 50 else "Needs attention")
    return {
        "business_id": business_id, "match_id": match_id, "business_name": biz.get("name"),
        "kind": kind, "score": score, "band": band,
        "data_source": "google_places" if _is_google(biz) else "seed",
        "pillars": {
            "relevance": "Category, services, posts, menu words, and language copy matched to what fans search.",
            "distance": "Where you are relative to fan flow — structural, but Posts and ads extend reach.",
            "prominence": "Reviews, rating, photos, reputation and web mentions, earned over time.",
        },
        "components": comps,
        "controllable_fixes": [{"action": c["recommended_fix"], "why": c["reason"],
                                "component": c["label"], "weight": c["weight"]} for c in controllable],
        "structural_factors": structural,
        "unknowns": unknowns,
        "distance_to_venue_km": (round(dist, 1) if dist is not None else None),
        "disclaimer": "FanFlow does not guarantee Google rank and rank cannot be bought. We identify the "
                      "profile, content, review, and conversion gaps that make it harder for matchday "
                      "visitors to find and choose your business.",
    }


# ── 2. Google Business Profile audit ─────────────────────────────────────────
def gbp_audit(business_id: str) -> dict:
    """Field-by-field GBP audit from real Google data — present/absent + the fix, then top-5."""
    biz = mongo.get_business(business_id) or {}
    gbp = biz.get("gbp", {}) or {}
    photos = gbp.get("photos", biz.get("photos", 0)) or 0
    checks = [
        ("primary_category", bool(biz.get("category")), True, "Set the most accurate primary category"),
        ("secondary_categories", bool(biz.get("secondary_categories")), True, "Add relevant secondary categories"),
        ("website", bool(biz.get("website")), True, "Add your website"),
        ("phone", bool(biz.get("phone")), True, "Add a phone number fans can tap to call"),
        ("hours", bool(biz.get("hours")), True, "Add regular hours"),
        ("special_hours", "special_hours" not in set(gbp.get("missing", [])) and bool(biz.get("special_hours_dates")),
         True, "Publish matchday special hours"),
        ("menu_link", bool(gbp.get("has_menu_link")), True, "Add a menu link"),
        ("reservation_order_link", bool(gbp.get("has_reservation_link")), True, "Add a reservation/order link"),
        ("photos_10plus", photos >= 10, True, f"Add photos (you have {photos}; aim for 10+ recent)"),
        ("rating", biz.get("rating") is not None, False, "Earned via service quality"),
        ("review_count", (biz.get("reviews") or 0) > 0, True, "Ask ALL recent customers for an honest review (asking only happy ones is gating — against Google policy)"),
        ("business_description", bool(biz.get("editorial_summary")), True, "Add a clear business description"),
        ("attributes", any(biz.get(a) is not None for a in
                           ("dine_in", "takeout", "good_for_groups", "serves_beer")), True,
         "Confirm attributes (dine-in, takeout, good for groups…)"),
    ]
    checklist = [{"field": f, "present": p, "fixable": fx, "fix": (None if p else fix)}
                 for f, p, fx, fix in checks]
    top = [c for c in checklist if not c["present"] and c["fixable"]][:5]
    return {
        "business_id": business_id, "business_name": biz.get("name"),
        "data_source": "google_places" if _is_google(biz) else "seed",
        "checklist": checklist,
        "top_fixes": [c["fix"] for c in top] or ["Profile looks complete — keep it fresh with Posts and photos"],
        "note": "These are the top fixes that can help more fans find and choose you. We never guarantee rank.",
    }


# ── 3. Matchday Post generator ───────────────────────────────────────────────
def generate_matchday_posts(business_id: str, match_id: str) -> dict:
    """Ready-to-publish Google Business Profile posts (English + languages with aggregate
    demand). Category-specific. The owner copies these into their profile."""
    biz = mongo.get_business(business_id) or {}
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    kind = business_kind(biz)
    ctx = {"home": ev.get("team_home_name", "the home team"), "away": ev.get("team_away_name", "the visitors"),
           "venue": ev.get("venue_name", "the stadium"), "nb": (biz.get("neighborhood_id") or "downtown").replace("_", " ")}
    cta = "Reserve" if biz.get("gbp", {}).get("has_reservation_link") else ("Call" if biz.get("phone") else "Directions")
    posts = [{"lang": "en", "title": a.format(**ctx),
              "body": PLAYBOOK[kind]["descriptions"][0].format(**ctx), "cta": cta}
             for a in PLAYBOOK[kind]["post_angles"][:3]]
    variants = []
    for lg in _demand_langs(mix):
        if lg in POST_I18N:
            body, _ = scrub_text(POST_I18N[lg].format(**ctx))
            variants.append({"lang": lg, "body": body, "cta": cta})
    return {
        "business_id": business_id, "kind": kind, "posts": posts, "language_variants": variants,
        "note": "Language variants are based on AGGREGATE language demand for this match — never a "
                "visitor's identity or nationality. Publish these as Google Business Profile Posts.",
    }


# ── 4. Review Assistant (never fabricates reviews) ───────────────────────────
_POS_WORDS = ("great", "love", "loved", "amazing", "best", "delicious", "friendly", "excellent", "perfect")
_NEG_WORDS = ("slow", "rude", "cold", "wait", "dirty", "worst", "bad", "overpriced", "disappointed")


def respond_to_review(business_id: str, review_text: str, rating: int | None = None) -> dict:
    """Draft a polite owner response to a REAL review. Never invents facts; mirrors only what the
    reviewer said. Tone follows sentiment."""
    biz = mongo.get_business(business_id) or {}
    name = biz.get("name", "our team")
    t = (review_text or "").lower()
    pos = sum(w in t for w in _POS_WORDS)
    neg = sum(w in t for w in _NEG_WORDS)
    sentiment = "negative" if (rating is not None and rating <= 2) or neg > pos else \
                "positive" if (rating is not None and rating >= 4) or pos > neg else "neutral"
    if sentiment == "positive":
        resp = (f"Thank you so much for the kind words! We're thrilled you enjoyed your visit to {name}. "
                "Thanks for supporting a local business during the tournament — we'd love to welcome you back on another matchday.")
    elif sentiment == "negative":
        resp = (f"Thank you for the honest feedback, and we're sorry your experience at {name} fell short. "
                "We take this seriously and would like to make it right — please reach out so we can follow up. "
                "We're working to do better, especially during busy matchdays.")
    else:
        resp = (f"Thanks for taking the time to review {name}. We appreciate the feedback and hope to see you "
                "again during the tournament.")
    clean, _ = scrub_text(resp)
    return {"business_id": business_id, "sentiment": sentiment, "response": clean,
            "guardrail": "This is a suggested reply to a REAL review. FanFlow never writes or posts fake reviews."}


def generate_review_request(business_id: str, match_id: str = "") -> dict:
    """Ethical review-REQUEST copy the owner can hand to ALL customers (multilingual by
    aggregate demand). Honest reviews only — never gated by sentiment, incentivized, or fake.
    Google's sanctioned method is a review link / QR code shared with every customer."""
    mix = mongo.get_source_market_mix(match_id) if match_id else {}
    variants = {"en": REVIEW_REQUEST_I18N["en"]}
    for lg in _demand_langs(mix or {}):
        if lg in REVIEW_REQUEST_I18N:
            variants[lg] = REVIEW_REQUEST_I18N[lg]
    return {"business_id": business_id, "request_copy": variants,
            "method": "Share Google's official review link or QR code with every customer.",
            "guardrail": "Ask EVERY customer for an honest review — never gate by sentiment (asking only "
                         "happy customers is prohibited), never offer payment/discounts, never "
                         "gate by rating, never fabricate — all against Google policy."}


def summarize_review_themes(business_id: str) -> dict:
    """Summarize themes from REAL public review snippets (if we have them); flag complaints that
    could hurt matchday conversion. 'Not enough signal' when we have no review text."""
    from .review_understanding import analyze_reviews
    rev = analyze_reviews(business_id)
    if not rev.get("available"):
        return {"business_id": business_id, "available": False,
                "message": "Not enough signal — no public review text on file to summarize.",
                "themes": [], "complaints": []}
    cues = rev.get("cues", {}) or {}
    theme_labels = {"local_favorite": "Locals call it a favorite", "hidden_gem": "Seen as a hidden gem",
                    "family_friendly": "Family-friendly", "soccer": "Mentioned for watching soccer",
                    "value": "Good value"}
    complaint_labels = {"parking_complaint": "Parking is a pain point",
                        "overrated": "Some feel it's overrated/overpriced"}
    return {
        "business_id": business_id, "available": True,
        "local_sentiment": rev.get("local_sentiment"), "confidence": rev.get("confidence"),
        "themes": [theme_labels[c] for c in cues if c in theme_labels],
        "complaints": [complaint_labels[c] for c in cues if c in complaint_labels],
        "note": "Themes from real public reviews. Address complaints before matchday to protect conversion.",
    }


# ── 5. Google Ads helper (category-specific, privacy-safe) ───────────────────
def ads_helper(business_id: str, match_id: str) -> dict:
    biz = mongo.get_business(business_id) or {}
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    kind = business_kind(biz)
    ctx = {"home": ev.get("team_home_name", "the home team"), "away": ev.get("team_away_name", "the visitors"),
           "venue": ev.get("venue_name", "the stadium"), "nb": (biz.get("neighborhood_id") or "downtown").replace("_", " ")}
    pb = PLAYBOOK[kind]
    headlines = [h.format(**ctx)[:30] for h in pb["headlines"]]
    descriptions = [d.format(**ctx)[:90] for d in pb["descriptions"]]
    lang_variants = [{"lang": lg, "headline": (POST_I18N[lg].format(**ctx)[:30])}
                     for lg in _demand_langs(mix) if lg in POST_I18N]
    return {
        "business_id": business_id, "kind": kind,
        "geo_targeting": ["10-minute walkshed of the stadium / fan zone",
                          f"{ctx['nb']} spillover band", "hotel clusters", "transit corridors (VTA/Caltrain)"],
        "intent_themes": [f"{kind} near {ctx['venue']}", "pre-match dining", "post-match late-night",
                          "world cup watch party", "near me"],
        "headlines": headlines,
        "descriptions": descriptions,
        "sitelinks": ["Menu", "Reserve / Order", "Directions", "Matchday Hours"],
        "callouts": ["Open Matchday", "Group Tables", "Fast Service", "Walk to Stadium"],
        "language_variants": lang_variants,
        "conversion_focus": pb["conversion"],
        "landing_checklist_ref": "Run /api/growth/landing before spending — ad clicks waste budget on a weak page.",
        "safe_audience": "geography + interface language + match timing + 'near me' intent",
        "never": "NEVER ethnicity, race, religion, or individual nationality (Google sensitive-category policy).",
        "quality_score_note": "Google Ads Quality Score is a 1–10 DIAGNOSTIC (expected CTR, ad relevance, "
                              "landing-page experience), not a direct auction input. Better performance comes "
                              "from relevance, landing-page quality, assets, and smart geo/language/intent "
                              "targeting — not just a higher bid.",
        "results_note": "This is readiness, not a guarantee of results.",
    }


# ── 6. Landing-page readiness ────────────────────────────────────────────────
def landing_page_readiness(business_id: str) -> dict:
    """Checklist of what an ad's landing page needs. We can confirm a few items from data
    (website/phone/links); page-content items are self-check (we don't crawl the site)."""
    biz = mongo.get_business(business_id) or {}
    website = biz.get("website")
    if not website:
        return {"business_id": business_id, "has_website": False, "score": None,
                "message": "Not enough signal — add a website first, then we can assess landing-page readiness.",
                "checklist": []}
    gbp = biz.get("gbp", {}) or {}
    known = [
        {"item": "Has a website", "status": "yes", "source": "google_places"},
        {"item": "Clickable phone number", "status": ("yes" if biz.get("phone") else "no"), "source": "google_places"},
        {"item": "Menu link available", "status": ("yes" if gbp.get("has_menu_link") else "unknown"), "source": "google_places"},
        {"item": "Reservation/order button", "status": ("yes" if gbp.get("has_reservation_link") else "unknown"), "source": "google_places"},
    ]
    self_check = [{"item": i, "status": "verify", "source": "self_check"} for i in [
        "Menu / key info visible above the fold", "Matchday hours shown clearly",
        "Directions / map embedded", "Mobile-friendly layout", "Loads fast (<3s)",
        "Clear matchday offer / call-to-action", "Language copy matches aggregate demand"]]
    confirmable = known
    yes = sum(1 for c in confirmable if c["status"] == "yes")
    score = round(100 * yes / len(confirmable))
    return {
        "business_id": business_id, "has_website": True, "website": website, "score": score,
        "confirmed": known, "self_check": self_check,
        "note": "We confirm what public data shows; page-content items are self-check (we don't crawl your site). "
                "A landing page that matches the ad is one of the biggest fixable wins for small ad budgets.",
    }


# ── Combined coach payload (one call for the UI) ─────────────────────────────
def growth_coach(business_id: str, match_id: str) -> dict:
    biz = mongo.get_business(business_id) or {}
    if not biz:
        return {"error": "business not found", "business_id": business_id}
    ev = mongo.get_event(match_id) or {}
    return {
        "business_id": business_id, "business_name": biz.get("name"),
        "match": f"{ev.get('team_home_name','')} vs {ev.get('team_away_name','')}".strip(" vs"),
        "kind": business_kind(biz),
        "readiness": matchday_search_readiness(business_id, match_id),
        "gbp_audit": gbp_audit(business_id),
        "posts": generate_matchday_posts(business_id, match_id),
        "ads": ads_helper(business_id, match_id),
        "landing": landing_page_readiness(business_id),
        "reviews": {
            "summary": summarize_review_themes(business_id),
            "request_copy": generate_review_request(business_id, match_id),
        },
        "privacy_note": "Everything here uses aggregate geo, language, match-timing and intent signals only. "
                        "No ethnicity, no individual identity, no fabricated reviews or ratings.",
    }
