"""get_google_trends — search-interest validation via pytrends (unofficial, free).

Used to corroborate which keyword clusters are actually heating up for a match.
Rate-limited and occasionally flaky -> always degrades to a seeded estimate.
"""
from __future__ import annotations

# Seeded fallback interest (0-100) keyed by theme, for offline/rate-limited demos.
_FALLBACK = {
    "mexican restaurant near stadium": 74,
    "late night food san jose": 58,
    "parking near levis stadium": 81,
    "world cup watch party san jose": 67,
    "taqueria downtown san jose": 49,
    "coffee near santa clara": 33,
}


def get_google_trends(keywords: list[str], geo: str = "US-CA", timeframe: str = "now 7-d") -> dict:
    """Return recent relative search interest per keyword."""
    keywords = keywords[:5] or list(_FALLBACK.keys())[:5]
    try:
        from pytrends.request import TrendReq
        py = TrendReq(hl="en-US", tz=420)
        py.build_payload(keywords, geo=geo, timeframe=timeframe)
        df = py.interest_over_time()
        if df is None or df.empty:
            raise RuntimeError("empty trends frame")
        out = {kw: int(df[kw].tail(3).mean()) for kw in keywords if kw in df}
        return {"geo": geo, "timeframe": timeframe, "interest": out, "source": "pytrends"}
    except Exception as e:
        out = {kw: _FALLBACK.get(kw.lower(), 50) for kw in keywords}
        return {"geo": geo, "timeframe": timeframe, "interest": out, "source": "fallback", "error": str(e)}
