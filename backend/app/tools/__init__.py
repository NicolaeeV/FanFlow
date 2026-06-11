"""Agent tools. Each is a plain function the ADK agent can call directly, and is also
re-exported for the deterministic /plan fallback in the FastAPI server."""
from .places import get_business_profile
from .weather import get_weather
from .trends import get_google_trends
from .forecast import forecast_foot_traffic
from .recommend import (
    recommend_inventory,
    recommend_google_ads_plan,
    generate_google_business_profile_updates,
    generate_multilingual_landing_page_copy,
    create_owner_action_plan,
)
from .signals import get_visitor_signals
from .visitor_intent_learning import learn_visitor_intents
from .visibility import compute_visibility_score
from .classify import classify_business
from .home_score import home_away_score
from .routing import route_local_favorites
from .funnel import search_to_revenue_funnel
from .visitor import recommend_for_visitor
from .profitability import forecast_profitability
from .zones import get_zone_graph
from .discovery import discover_fan_venues
from .recent_signals import recent_demand_changes
from .trip_model import estimate_visitor_mix_and_stay
from .itinerary import build_match_day_itinerary
# natural-language understanding + review evidence
from .text_understanding import understand_text
from .review_understanding import analyze_reviews
from .nlu import analyze as nlu_analyze
from .food_safety import detect_food_constraints, check_place_food
from .place_truth import place_status
from .evidence import build_evidence
from .review_understanding import sanitize_external_text
from .hours import parse_requested_time, is_open_at, hours_for_day
from .open_hours import assess_open_hours, viable_for_stage
from .capacity import estimate_capacity
from .soccer_relevance import soccer_relevance
from .fan_journey import detect_stage, STAGE_POLICY
from .google_crawler_security import (is_google_crawler_ip, verify_googlebot_request,
                                      load_google_ip_ranges, refresh_from_google)
from .google_places_connector import get_place_live, normalize_business_status, fetch_place_details
from .transit_connector import get_route, fetch_service_alerts
from .route_planner import assess_route, refine_slot_tradeoff, TRADEOFF_LABELS
from . import neighborhoods
from .neighborhoods import (get_neighborhood, vicinity_label, realistic_for_stage,
                            distance_to_stadium_km, nearest_neighborhood, NEIGHBORHOODS)
from . import special_hours
from .special_hours import special_day_info, holiday_name, HOLIDAYS_2026
from . import hours_providers
from .hours_providers import live_hours, live_open_now, provider_status, PROVIDERS
from . import routing_providers
from .routing_providers import live_eta
from . import tourism_trends
from .tourism_trends import (zone_shopping_profile, zone_profiles, where_locals_shop,
                             tourist_demand_zones, origin_inference_allowed)
from . import local_discovery
from .local_discovery import is_independent_osm, local_gem_heuristic, gem_candidates
from . import demand_influx
from .demand_influx import influx_signal
from . import replay_backtest
from .replay_backtest import run_replay
from .weather_connector import match_window_weather
from .soccer_source_connector import collect_soccer_evidence
from . import owner_connectors
from .source_catalog import (SOURCE_CATALOG, is_source_allowed, get_allowed_sources,
                             label_evidence, requires_verification, can_store, integration_status)
# probabilistic visitor-understanding layer
from .visitor_state_model import infer_visitor_intent
from .markov_trip_model import predict_trip
from .choice_model import score_places
from .hidden_gem_score import hidden_gem_score
from .friedman_preference_tests import run_preference_demo
from .chat_planner import plan_visitor_chat
from .business_tags import (infer_business_tags, is_food_eligible, expand_query_tags,
                            why_matched_phrase, FOOD_TAG_UNIVERSE)
from .growth_coach import (growth_coach, matchday_search_readiness, gbp_audit,
                           generate_matchday_posts, respond_to_review, generate_review_request,
                           summarize_review_themes, ads_helper, landing_page_readiness,
                           business_kind)
from .business_intel import business_intelligence, rank_businesses, hidden_gems, is_chain, hidden_gems, is_chain
from .learning_loop import log_feedback as record_feedback, learned_adjustments
from .. import mongo

__all__ = [
    "get_business_profile",
    "get_weather",
    "get_google_trends",
    "forecast_foot_traffic",
    "recommend_inventory",
    "recommend_google_ads_plan",
    "generate_google_business_profile_updates",
    "generate_multilingual_landing_page_copy",
    "create_owner_action_plan",
    "get_match_schedule",
    "get_source_market_mix",
    "search_businesses_semantic",
    # demand-routing-engine modules
    "get_visitor_signals",
    "learn_visitor_intents",
    "compute_visibility_score",
    "classify_business",
    "home_away_score",
    "route_local_favorites",
    "search_to_revenue_funnel",
    "recommend_for_visitor",
    "forecast_profitability",
    # discovery + routing graph (scrape/learn building blocks)
    "get_zone_graph",
    "discover_fan_venues",
    "recent_demand_changes",
    "estimate_visitor_mix_and_stay",
    "build_match_day_itinerary",
    # NLU + review evidence
    "understand_text",
    "analyze_reviews",
    "nlu_analyze",
    "detect_food_constraints",
    "check_place_food",
    "place_status",
    "build_evidence",
    "sanitize_external_text",
    "parse_requested_time",
    "is_open_at",
    "hours_for_day",
    "assess_open_hours",
    "viable_for_stage",
    "estimate_capacity",
    "soccer_relevance",
    "detect_stage",
    "is_google_crawler_ip",
    "verify_googlebot_request",
    "load_google_ip_ranges",
    "refresh_from_google",
    "get_place_live",
    "normalize_business_status",
    "fetch_place_details",
    "get_route",
    "assess_route",
    "refine_slot_tradeoff",
    "TRADEOFF_LABELS",
    "neighborhoods",
    "get_neighborhood",
    "vicinity_label",
    "realistic_for_stage",
    "distance_to_stadium_km",
    "nearest_neighborhood",
    "NEIGHBORHOODS",
    "special_hours",
    "special_day_info",
    "holiday_name",
    "HOLIDAYS_2026",
    "hours_providers",
    "live_hours",
    "live_open_now",
    "provider_status",
    "PROVIDERS",
    "routing_providers",
    "live_eta",
    "tourism_trends",
    "zone_shopping_profile",
    "zone_profiles",
    "where_locals_shop",
    "tourist_demand_zones",
    "origin_inference_allowed",
    "local_discovery",
    "is_independent_osm",
    "local_gem_heuristic",
    "gem_candidates",
    "demand_influx",
    "influx_signal",
    "replay_backtest",
    "run_replay",
    "match_window_weather",
    "collect_soccer_evidence",
    "owner_connectors",
    "SOURCE_CATALOG",
    "is_source_allowed",
    "get_allowed_sources",
    "label_evidence",
    "requires_verification",
    "can_store",
    "integration_status",
    # probabilistic visitor-understanding layer
    "infer_visitor_intent",
    "predict_trip",
    "score_places",
    "hidden_gem_score",
    "run_preference_demo",
    "plan_visitor_chat",
    "infer_business_tags",
    "is_food_eligible",
    "expand_query_tags",
    "why_matched_phrase",
    "FOOD_TAG_UNIVERSE",
    # Google Growth Coach
    "growth_coach",
    "matchday_search_readiness",
    "gbp_audit",
    "generate_matchday_posts",
    "respond_to_review",
    "generate_review_request",
    "summarize_review_themes",
    "ads_helper",
    "landing_page_readiness",
    "business_kind",
    "business_intelligence",
    "rank_businesses",
    "hidden_gems",
    "is_chain",
    "record_feedback",
    "learned_adjustments",
]


def get_match_schedule(city: str = "bay_area", event_id: str = "") -> dict:
    """Return upcoming World Cup matches for a host city (or one event by id)."""
    if event_id:
        ev = mongo.get_event(event_id)
        return {"events": [ev] if ev else []}
    return {"events": mongo.get_events(city)}


def get_source_market_mix(event_id: str) -> dict:
    """Aggregate, k-anonymous country/language/party mix for a match. NOT ethnicity."""
    mix = mongo.get_source_market_mix(event_id)
    return mix or {"error": "no source-market mix for event", "event_id": event_id}


def search_businesses_semantic(query: str, neighborhood_id: str = "") -> dict:
    """Business search via Atlas Vector Search (MCP vectorSearch parity), with a KEYWORD/TAG
    fallback. Vector search needs embeddings (a GCP/Gemini project); when that isn't configured the
    vector call returns nothing — without the fallback the agent would wrongly say "I have no data"
    for places that plainly exist. The fallback matches the query's cuisine tags + name/category
    terms over the (cached) business set so discovery works regardless of the embeddings setup."""
    from .recommend import embed_text
    vec = embed_text(query)
    results = mongo.vector_search_businesses(vec, k=8, neighborhood_id=neighborhood_id or None)
    source = "vector"
    if not results:
        source = "keyword"
        results = _keyword_business_search(query, neighborhood_id or None, k=8)
    return {"query": query, "results": results, "source": source}


_SEARCH_STOP = {"near", "the", "a", "an", "by", "at", "in", "good", "best", "spot", "spots", "place",
                "places", "food", "restaurant", "restaurants", "stadium", "levis", "levi", "around",
                "me", "some", "for", "with", "and", "to", "of", "want", "find"}


def _keyword_business_search(query: str, neighborhood_id, k: int = 8) -> list:
    """Embeddings-free discovery: match the query's expanded cuisine tags and name/category terms
    against food-eligible, open businesses; return the top-rated. Real data, no vector index."""
    import re as _re
    from .business_tags import expand_query_tags, infer_business_tags, is_food_eligible
    from .hidden_gem_score import bayesian_rating
    qtags = expand_query_tags(query or "")
    terms = [w for w in _re.findall(r"[a-z]{3,}", (query or "").lower()) if w not in _SEARCH_STOP]
    scored = []
    for b in mongo.get_businesses(neighborhood_id):
        if b.get("business_status") == "closed" or not is_food_eligible(b):
            continue
        tags = set(infer_business_tags(b, use_reviews=False).get("tags", []))
        name, cat = (b.get("name") or "").lower(), (b.get("category") or "")
        if (qtags & tags) or any(t in name or t in cat for t in terms):
            # rank by BIAS-CORRECTED (Bayesian) rating, not raw stars — otherwise a 5.0★ with 3
            # reviews outranks a 4.7★ with 2000 (the exact review-volume bias the product fights).
            bayes = bayesian_rating(b.get("rating"), b.get("reviews") or 0)
            scored.append((bayes, b))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _, b in scored:  # dedup duplicate listings of the same place by name
        key = (b.get("name") or "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"_id": b.get("_id"), "name": b.get("name"), "category": b.get("category"),
                    "rating": b.get("rating"), "neighborhood_id": b.get("neighborhood_id")})
        if len(out) >= k:
            break
    return out
