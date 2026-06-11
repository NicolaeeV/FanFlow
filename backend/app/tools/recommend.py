"""Recommendation builders + plan assembly.

Each builder produces an owner-approvable DRAFT. They use Gemini when available and
degrade to deterministic rule-based drafts otherwise (so the demo always works).
Everything is run through guardrails.policy_check() in create_owner_action_plan().
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone

from ..config import GCP_PROJECT, GCP_LOCATION, GEMINI_MODEL
from ..prompts import RECO_GUARDRAIL
from ..guardrails import policy_check
from .. import mongo
from .forecast import forecast_foot_traffic
from .weather import get_weather
from .visibility import compute_visibility_score
from .visitor_intent_learning import learn_visitor_intents
from .profitability import forecast_profitability
from .home_score import home_away_score
from .funnel import search_to_revenue_funnel
from .open_hours import assess_open_hours
from .capacity import estimate_capacity
from .soccer_relevance import soccer_relevance


# ── Gemini helpers ───────────────────────────────────────────────────────────
_GENAI_CLIENT: object = "uninit"   # cache: created once, not per call


def _genai_client():
    """Vertex AI genai client, created lazily and CACHED. Without a GCP project we skip
    construction entirely — otherwise genai.Client() spends ~14s timing out on ADC credential
    discovery on every call (e.g. once per embedding), which made seeding crawl for ~an hour."""
    global _GENAI_CLIENT
    if _GENAI_CLIENT != "uninit":
        return _GENAI_CLIENT
    try:
        if not GCP_PROJECT:
            _GENAI_CLIENT = None
        else:
            from google import genai
            _GENAI_CLIENT = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)
    except Exception:
        _GENAI_CLIENT = None
    return _GENAI_CLIENT


def _gemini_json(prompt: str) -> dict | None:
    client = _genai_client()
    if client is None:
        return None
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"{RECO_GUARDRAIL}\n\n{prompt}\n\nReturn ONLY valid minified JSON.",
            config={"response_mime_type": "application/json", "temperature": 0.4},
        )
        return json.loads(resp.text)
    except Exception:
        return None


def embed_text(text: str, dim: int = 1536) -> list[float]:
    """Embedding for Atlas Vector Search. Uses Gemini embeddings; falls back to a
    deterministic hash-based pseudo-vector so seeding/search works offline."""
    client = _genai_client()
    if client is not None:
        try:
            r = client.models.embed_content(model="text-embedding-004", contents=text)
            return list(r.embeddings[0].values)
        except Exception:
            pass
    # deterministic fallback vector (NOT semantically meaningful, demo only)
    h = hashlib.sha256(text.encode()).digest()
    return [((h[i % len(h)] / 255.0) * 2 - 1) for i in range(dim)]


# ── builders ─────────────────────────────────────────────────────────────────
def recommend_inventory(business_id: str, match_id: str) -> dict:
    biz = mongo.get_business(business_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    wx = get_weather()
    cat = biz.get("category", "default")
    langs = [l["lang"] for l in mix.get("language_mix", [])[:3]]

    g = _gemini_json(
        f"Business category: {cat}. Aggregate language mix (NOT ethnicity): {langs}. "
        f"Weather hint: {wx.get('inventory_hint')}. Suggest 4-6 inventory increases for a "
        f"World Cup match-day surge as JSON list of objects {{item, increase_pct, why}}. "
        f"Ethical pricing only."
    )
    if g and isinstance(g.get("inventory"), list):
        return {"inventory": g["inventory"]}

    # rule-based fallback
    base = []
    if "mexican" in cat:
        base = [{"item": "tortillas/masa", "increase_pct": 45, "why": "high family-group demand"},
                {"item": "michelada mix & beer", "increase_pct": 35, "why": "watch-party beverage"},
                {"item": "to-go containers", "increase_pct": 40, "why": "post-match takeout wave"}]
    elif cat in ("sports_bar", "bar"):
        base = [{"item": "draft beer kegs", "increase_pct": 50, "why": "pre+post match peak"},
                {"item": "wings/shareables", "increase_pct": 40, "why": "group dwell time"}]
    elif cat in ("convenience_store", "grocery"):
        base = [{"item": "bottled water", "increase_pct": 15, "why": "hydration (ethical, capped)"},
                {"item": "phone chargers", "increase_pct": 30, "why": "fan essentials"},
                {"item": "snacks", "increase_pct": 35, "why": "walk-to-stadium traffic"}]
    else:
        base = [{"item": "top sellers", "increase_pct": 30, "why": "general surge"},
                {"item": "to-go packaging", "increase_pct": 35, "why": "takeout wave"}]
    if wx.get("inventory_hint") == "rain_gear":
        base.append({"item": "ponchos/umbrellas", "increase_pct": 25, "why": "rain forecast"})
    return {"inventory": base}


def recommend_google_ads_plan(business_id: str, match_id: str) -> dict:
    biz = mongo.get_business(business_id) or {}
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    cat = biz.get("category", "business")
    venue = ev.get("venue_name", "the stadium")
    nb = biz.get("neighborhood_id", "downtown")
    langs = [l["lang"] for l in mix.get("language_mix", [])[:2]]

    clusters = [
        {"theme": "pre-match dining/visit",
         "keywords": [f"{cat.replace('_',' ')} near {venue}", f"pre game food {nb}", f"restaurants near {venue}"]},
        {"theme": "post-match late-night",
         "keywords": [f"late night food {nb}", f"open after the game {nb}", "post match food near me"]},
        {"theme": "intent + match context",
         "keywords": [f"world cup watch party {nb}", f"{ev.get('team_home_name','team')} game food", "near fan zone"]},
    ]
    if "es" in langs:
        clusters.append({"theme": "spanish-language intent (language, not ethnicity)",
                         "keywords": ["comida cerca del estadio", "donde ver el partido san jose"]})
    if "pt" in langs:
        clusters.append({"theme": "portuguese-language intent (language, not ethnicity)",
                         "keywords": ["comida perto do estadio", "onde assistir o jogo"]})
    return {
        "campaign": "Search + location assets (+ Performance Max for store goals if multi-location)",
        "budget_share": 0.4,
        "geo_design": ["10-min walkshed of venue/fan-zone", f"{nb} spillover band", "transit nodes (VTA/Caltrain)"],
        "bid_strategy": "Maximize Conversions / tCPA once volume exists; lean on location+language+time signals",
        "keyword_clusters": clusters,
        "safe_audience": "geography + interface language + match timing + 'near me' intent",
        "negative_safe_audience": "NEVER ethnicity or individual nationality",
        "creative_example": f"Open late for the match — {cat.replace('_',' ')} near {venue}. Directions · Call · Reserve",
    }


def generate_google_business_profile_updates(business_id: str, match_id: str) -> dict:
    biz = mongo.get_business(business_id) or {}
    ev = mongo.get_event(match_id) or {}
    gaps = (biz.get("gbp") or {}).get("missing", []) or biz.get("gbp_gaps", [])
    return {
        "post": {
            "title": f"Open late for {ev.get('team_home_name','the')} match day",
            "body": "Match-day specials + extended hours. Reserve or call ahead.",
            "cta": "Reserve" if (biz.get("gbp") or {}).get("has_reservation_link") else "Call",
        },
        "readiness_checklist": [
            *( ["Add a menu link to your profile"] if "menu_link" in gaps else [] ),
            *( ["Add a reservation link"] if "reservation_link" in gaps else [] ),
            *( ["Add 10+ recent photos"] if "photos" in gaps or "few_photos" in gaps else [] ),
            "Set special hours for match day (extend to post-match wave)",
            "Confirm primary category and attributes (wifi, outdoor seating, takeout)",
        ],
    }


def generate_multilingual_landing_page_copy(business_id: str, match_id: str) -> dict:
    biz = mongo.get_business(business_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    langs = [l["lang"] for l in mix.get("language_mix", []) if l["lang"] != "en"][:2]
    name = biz.get("name", "Our place")
    snippets = {"en": f"{name}: open late for the match — fast service, group tables, walk from the stadium."}
    templates = {
        "es": f"{name}: abierto hasta tarde para el partido — servicio rápido, mesas para grupos, a poca distancia del estadio.",
        "pt": f"{name}: aberto até tarde para o jogo — serviço rápido, mesas para grupos, perto do estádio.",
        "ar": f"{name}: مفتوح حتى وقت متأخر لمباراة كأس العالم — خدمة سريعة وطاولات للمجموعات.",
    }
    for lg in langs:
        if lg in templates:
            snippets[lg] = templates[lg]
    return {"landing_copy": snippets, "note": "Language targeting is operational, not identity-based."}


def _staffing_from_forecast(fc: dict, category: str) -> list[dict]:
    out = []
    for h in fc.get("hours", []):
        lift = h.get("lift_vs_normal_pct", 0)
        base_staff = 3 if category in ("cafe", "convenience_store") else 4
        staff = max(base_staff, round(base_staff * (1 + lift / 100.0)))
        out.append({"hour": h["hour_local"], "staff": staff,
                    "expected_walkins": h["expected_walkins_p50"]})
    return out


def create_owner_action_plan(business_id: str, match_id: str) -> dict:
    """Assemble the full action plan from all builders, run guardrails, save to Mongo."""
    biz = mongo.get_business(business_id) or {}
    ev = mongo.get_event(match_id) or {}
    mix = mongo.get_source_market_mix(match_id) or {}
    cat = biz.get("category", "business")

    # Grounding + brittleness guard: never assemble a full owner action plan for a business or
    # match that doesn't exist — that would fabricate staffing/inventory/revenue for nothing.
    # Return an honest, fast error (also avoids the downstream max() over an empty forecast).
    if not biz or not ev:
        missing = ", ".join(m for m, ok in (("business", biz), ("match", ev)) if not ok)
        return {"business_id": business_id, "event_id": match_id,
                "error": "unknown_business_or_match", "detail": f"not found: {missing}"}

    fc = forecast_foot_traffic(business_id, match_id)
    inv = recommend_inventory(business_id, match_id)["inventory"]
    ads = recommend_google_ads_plan(business_id, match_id)
    gbp = generate_google_business_profile_updates(business_id, match_id)
    land = generate_multilingual_landing_page_copy(business_id, match_id)
    vis = compute_visibility_score(business_id, match_id)
    intel = learn_visitor_intents(match_id, business_id)
    prof = forecast_profitability(business_id, match_id)
    funnel = search_to_revenue_funnel(business_id, match_id)
    demand_langs = {l["lang"] for l in mix.get("language_mix", [])
                    if l["lang"] not in ("en", "other") and l.get("share", 0) >= 0.1}
    home = home_away_score(biz, ev, demand_langs)

    # `or [...]` (not just get-default): the forecast can legitimately carry an EMPTY hours list,
    # and max([]) raises. Fall back to a neutral peak so the plan still assembles.
    peak = max(fc.get("hours") or [{"lift_vs_normal_pct": 0, "hour_local": "19:00"}],
               key=lambda x: x.get("lift_vs_normal_pct", 0))
    langs = [l["lang"] for l in mix.get("language_mix", [])[:3]]

    # revenue lift now comes from the profitability conversion-chain model.
    lift_low = prof["incremental_revenue_usd"]["low"]
    lift_high = prof["incremental_revenue_usd"]["high"]

    plan = {
        "_id": f"plan_{business_id}_{match_id}",
        "business_id": business_id, "event_id": match_id,
        "business_name": biz.get("name"), "category": cat,
        "match": f"{ev.get('team_home_name','?')} vs {ev.get('team_away_name','?')}",
        "kickoff_local": ev.get("kickoff_local"),
        "status": "draft",
        "generated_by": GEMINI_MODEL,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "forecast_peak": {"hour": peak["hour_local"], "lift_pct": peak.get("lift_vs_normal_pct")},
        "hourly": fc["hours"],
        "staffing": _staffing_from_forecast(fc, cat),
        "inventory": inv,
        "hours_change": "Extend close to ~1:00 AM to catch the post-match wave"
                        if cat in ("mexican_restaurant", "italian_restaurant", "sports_bar", "bar") else
                        "Open earlier / stay open through kickoff window",
        "menu_specials": [f"Pre-match prix fixe", "Post-match late-night menu"],
        "languages": langs,
        "gbp_post": f"{gbp['post']['title']} — {gbp['post']['body']} [{gbp['post']['cta']}]",
        "gbp_checklist": gbp["readiness_checklist"],
        "ads_plan": ads,
        "landing_copy": land["landing_copy"],
        "revenue_lift_usd": {"low": lift_low, "high": lift_high},
        "visibility_score": vis["visibility_score"],
        "visibility_components": vis["components"],
        "visibility_fixes": vis["controllable_fixes"],
        "visitor_intents": [
            {"label": i["label"], "seeks": i["seeks"],
             "confidence": i["confidence"]["level"], "status": i["confidence"]["status"],
             "score": i["confidence"]["score"],
             "top_evidence": [e["signal"] for e in i["evidence"] if e["supports"]][:3],
             "actions": i["recommended_actions"][:2], "fits_business": i["business_fit"]}
            for i in intel["intents"][:5]
        ],
        "signals_available": intel["first_party_signals"],
        "demand_signals": intel["signals_summary"],
        "still_unsure_about": intel["still_unsure_about"],
        "classification": home["classification"],
        "home_score": home["home_score"],
        "why_tourists_pick_you": home["why_recommended"],
        "how_to_be_chosen": home["how_to_improve"],
        "funnel": {"stages": funnel["stages"], "primary_leak": funnel["primary_leak"],
                   "summary": funnel["summary"]},
        "net_opportunity_usd": prof["net_opportunity_usd"],
        "profitability": prof,
        "confidence": fc["confidence"],
        "risks": [
            "stockout on top items if inventory not raised",
            "long waits / bad-review risk at peak hour",
            "price-gouging risk — keep increases ethical (<20%, no essentials)",
        ],
        "why": (
            f"{ev.get('team_home_name','The match')} is a marquee match "
            f"{fc.get('distance_to_venue_km')}km away; peak around {peak['hour_local']} "
            f"(+{peak.get('lift_vs_normal_pct')}%). Aggregate visitor demand skews "
            f"{', '.join(langs)}-language. Prep inventory, staffing, hours and your Google profile now."
        ),
    }
    # soccer-specific, match-day owner actions (conditioned on real viability/crowd signals)
    oh = assess_open_hours(biz, ev)
    cap = estimate_capacity(biz, ev)
    soc = soccer_relevance(biz)
    actions = [
        "Post a 'World Cup match-day hours' update on your Google Business Profile",
        "Add bilingual (EN/ES) match-day signage + a QR menu for faster ordering",
        "Stock extra bottled water & non-alcoholic drinks for families/kids",
        "Staff up for the pre- and post-match surge windows — and avoid price gouging",
    ]
    if oh["post_match_viable"] != "no":
        actions.append("Extend hours into the post-match wave and offer a late-night food bundle")
    else:
        actions.append("You close before the post-match wave — consider extended match-day hours to capture it")
    if cap["crowd_risk"] in ("high", "medium"):
        actions.append("Add a pickup/family line and a backup plan (to-go / overflow) — crowd risk is "
                       + cap["crowd_risk"])
    if soc["label"] in ("general_sports_bar", "candidate_soccer_spot", "verified_soccer_hub"):
        actions.append("If you legally can, show the match on screens and promote a watch-party")
    plan["soccer_match_day_actions"] = actions
    plan["match_day_open_hours"] = {k: oh[k] for k in ("post_match_viable", "late_night_viable",
                                                       "hours_source", "call_ahead_required")}
    plan["crowd_risk"] = cap["crowd_risk"]

    plan = policy_check(plan)
    mongo.save_action_plan(plan)
    return plan
