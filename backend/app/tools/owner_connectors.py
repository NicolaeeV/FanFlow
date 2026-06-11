"""Owner-authorized connectors (GA4 / GBP Performance / Google Ads / POS) — STUBS.

These require the business owner's OAuth/credentials. With none present they return
{available: False} and the agent falls back to forecast/seed. No competitor data, ever.
Ads is draft-only (no organic-ranking claims). Real data shapes are documented so wiring
is a drop-in once credentials exist.
"""
from __future__ import annotations
import os

GA4_PROPERTY = os.getenv("GA4_PROPERTY_ID", "")
GBP_OAUTH = os.getenv("GBP_OAUTH_TOKEN", "")
ADS_DEV_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
POS_TOKEN = os.getenv("POS_API_TOKEN", "")


def ga4_signals(business_id: str) -> dict:
    """GA4 Data API: sessions, realtime users, language, page/menu/order/reservation clicks."""
    if not GA4_PROPERTY:
        return {"available": False, "source": "ga4", "reason": "owner GA4 not connected",
                "fields": ["sessions", "realtimeUsers", "language", "menu_clicks",
                           "order_clicks", "reservation_clicks", "source_medium"]}
    return {"available": False, "source": "ga4", "reason": "ga4 client not implemented in MVP"}


def gbp_performance(business_id: str) -> dict:
    """GBP Performance API: calls, website clicks, direction requests, profile interactions."""
    if not GBP_OAUTH:
        return {"available": False, "source": "gbp", "reason": "owner GBP not connected",
                "fields": ["CALL_CLICKS", "WEBSITE_CLICKS", "BUSINESS_DIRECTION_REQUESTS",
                           "search_keywords"]}
    return {"available": False, "source": "gbp", "reason": "gbp client not implemented in MVP"}


def ads_draft(business_id: str, keyword_clusters: list | None = None) -> dict:
    """Google Ads: DRAFT campaign/keyword ideas only. Never an organic-ranking promise."""
    return {"available": bool(ADS_DEV_TOKEN), "source": "google_ads", "mode": "draft_only",
            "note": "Drafts only — organic Google rank can't be bought or guaranteed.",
            "keyword_clusters": keyword_clusters or []}


def pos_signals(business_id: str) -> dict:
    """POS/reservation: sales, wait time, capacity, sold-out — only if owner opted in."""
    if not POS_TOKEN:
        return {"available": False, "source": "pos", "reason": "POS not connected",
                "fields": ["sales", "wait_minutes", "capacity_pct", "sold_out"]}
    return {"available": False, "source": "pos", "reason": "pos client not implemented in MVP"}
