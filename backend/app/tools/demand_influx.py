"""Demand-influx signals — airport arrivals, hotel occupancy proxy, ticket resale curves.

Leading indicators of visitor volume, all AGGREGATE-ONLY by construction:
  - flight arrivals  → COUNTS by origin region ("N international arrivals") — never manifests
  - hotel rates      → zone-level rate/availability (rising price + falling rooms = demand
                       shock proxy) — never guest data
  - ticket resale    → public listing price/volume curves (a 48h-out spike = hardcore-fan
                       demand) — never buyer/seller identity

Every fetcher needs a key and returns aggregate numbers from a genuine call, or None.
OFFLINE / NO KEY → None → the caller reports "no influx signal yet" (an honest hypothesis to
monitor) — nothing is fabricated. The combined signal is always labeled a CANDIDATE demand
proxy, never a fact about any person.
"""
from __future__ import annotations
import os
from .source_catalog import integration_status

SOURCES = ["flight_arrivals", "hotel_rates", "ticket_resale"]
DISCLAIMER = ("Aggregate counts/rates/curves only — never passenger manifests, guest lists, "
              "or buyer identity.")


def source_status() -> dict:
    return {sid: integration_status(sid) for sid in SOURCES}


def airport_arrivals(airport: str = "SJC") -> dict | None:
    """Aggregate arrival counts for an airport (SJC/SFO/OAK). Live only with FLIGHT_API_KEY;
    None offline. Stores counts by origin region — never passenger data."""
    key = os.getenv("FLIGHT_API_KEY", "")
    if not key:
        return None
    try:
        import httpx
        r = httpx.get("https://api.flightapi.io/compschedule/" + key,
                      params={"mode": "arrivals", "iata": airport, "day": 1}, timeout=10)
        r.raise_for_status()
        flights = r.json() or []
        intl = sum(1 for f in flights if isinstance(f, dict) and f.get("international"))
        return {"airport": airport, "arrivals_total": len(flights),
                "arrivals_international": intl, "source": "flight_arrivals",
                "freshness": "live", "disclaimer": DISCLAIMER}
    except Exception:
        return None


def hotel_demand_proxy(zone_lat: float, zone_lon: float) -> dict | None:
    """Zone-level occupancy PROXY from aggregated rates/availability (Makcorps/Amadeus shape).
    Live only with HOTEL_RATES_API_KEY; None offline. Never guest-level data."""
    key = os.getenv("HOTEL_RATES_API_KEY", "")
    if not key:
        return None
    try:
        import httpx
        r = httpx.get("https://api.makcorps.com/mapping",
                      params={"api_key": key, "lat": zone_lat, "lon": zone_lon}, timeout=10)
        r.raise_for_status()
        rows = r.json() or []
        prices = [h.get("price") for h in rows if isinstance(h, dict) and h.get("price")]
        avail = sum(1 for h in rows if isinstance(h, dict) and h.get("available"))
        return {"hotels_sampled": len(rows), "rooms_available": avail,
                "median_rate": sorted(prices)[len(prices) // 2] if prices else None,
                "source": "hotel_rates", "freshness": "live", "disclaimer": DISCLAIMER}
    except Exception:
        return None


def ticket_resale_curve(event_query: str) -> dict | None:
    """Public resale listing price/volume for an event (TicketsData/SeatGeek shape). Live only
    with TICKETS_API_KEY; None offline. Listing data only — never buyer/seller identity."""
    key = os.getenv("TICKETS_API_KEY", "")
    if not key:
        return None
    try:
        import httpx
        r = httpx.get("https://api.seatgeek.com/2/events",
                      params={"client_id": key, "q": event_query, "per_page": 1}, timeout=10)
        r.raise_for_status()
        evs = (r.json() or {}).get("events") or []
        if not evs:
            return None
        st = evs[0].get("stats") or {}
        return {"listing_count": st.get("listing_count"),
                "median_price": st.get("median_price"), "lowest_price": st.get("lowest_price"),
                "source": "ticket_resale", "freshness": "live", "disclaimer": DISCLAIMER}
    except Exception:
        return None


def influx_signal(event: dict | None = None) -> dict:
    """Combined demand-influx signal for the owner forecast. Honest: with no keys it reports
    'no signal yet' (hypothesis to monitor) rather than inventing numbers."""
    ev = event or {}
    parts = {
        "airport": airport_arrivals("SJC"),
        "hotels": hotel_demand_proxy(ev.get("venue_lat", 37.4033), ev.get("venue_lon", -121.9694)),
        "tickets": ticket_resale_curve(f"{ev.get('team_home_name', '')} {ev.get('team_away_name', '')}".strip()),
    }
    live = {k: v for k, v in parts.items() if v}
    return {
        "available": bool(live),
        "signals": live,
        "confidence": "medium" if len(live) >= 2 else "low" if live else "none",
        "label": "candidate_demand_proxy",   # a leading indicator, never a fact about people
        "note": ("Influx signals live: " + ", ".join(live) if live else
                 "No influx signal yet — connect flight/hotel/ticket keys; demand stays a "
                 "hypothesis to monitor."),
        "disclaimer": DISCLAIMER,
    }
