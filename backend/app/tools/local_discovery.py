"""Honest-stack local-discovery heuristics — privacy-safe, no scraping, public aggregate only.

Two cheap, defensible signals that find "hidden gems" without tracking anyone:
  1. OSM independence — OpenStreetMap tags a chain with `brand` / `brand:wikidata`; an
     independent has none. So `shop=* AND brand:wikidata IS NULL` ≈ independent business.
  2. High-rating / low-review — tourist magnets have huge review volume at a middling rating;
     local gems have few reviews at a high rating. Uses ONLY the public aggregate rating +
     review COUNT (no review text, no individuals).

Both are CANDIDATE signals (never asserted as fact) — they complement the Bayesian
hidden_gem_score, and `classify`/`claim_validator` keep reputation candidate-gated.
"""
from __future__ import annotations

# OSM tags that mark a place as part of a chain/brand (so its absence ⇒ independent)
_OSM_CHAIN_TAGS = ("brand", "brand:wikidata", "brand:wikipedia", "operator:wikidata")


def is_independent_osm(tags: dict | None) -> bool:
    """OpenStreetMap independence: a place with no brand/chain tag is an independent business.
    This is how we'd filter chains out of an Overpass `shop=*` result, programmatically."""
    t = tags or {}
    return not any(t.get(k) for k in _OSM_CHAIN_TAGS)


def local_gem_heuristic(rating, reviews) -> dict:
    """High-rating + low-review ⇒ candidate local gem; high-volume + middling rating ⇒ likely
    tourist magnet. Public aggregate rating + review COUNT only — no scraping, no individuals.
    Always a CANDIDATE signal; never asserts a place IS a local favorite."""
    r = rating or 0
    n = reviews or 0
    candidate_gem = (r >= 4.7) and (0 < n < 150)
    tourist_magnet = (n >= 1000) and (r <= 4.3)
    if candidate_gem:
        signal, basis = "candidate_local_gem", f"{r}★ with only {n} reviews"
    elif tourist_magnet:
        signal, basis = "likely_tourist_magnet", f"{r}★ across {n} reviews"
    else:
        signal, basis = "none", "no strong signal either way"
    return {"signal": signal, "candidate_gem": candidate_gem, "tourist_magnet": tourist_magnet,
            "basis": basis, "verification": "candidate", "source": "public_aggregate_heuristic"}


def gem_candidates(places: list, limit: int = 10) -> list:
    """Rank independent places by the local-gem heuristic (candidate-only). Chains excluded —
    a chain can't be a hidden gem. Reputation stays a candidate signal to verify."""
    out = []
    for b in places or []:
        if b.get("chain"):
            continue
        h = local_gem_heuristic(b.get("rating"), b.get("reviews"))
        if h["candidate_gem"]:
            out.append({"place_id": b.get("_id"), "name": b.get("name"),
                        "rating": b.get("rating"), "reviews": b.get("reviews"),
                        "neighborhood_id": b.get("neighborhood_id"),
                        "signal": h["signal"], "basis": h["basis"], "verification": "candidate"})
    out.sort(key=lambda c: (c["rating"] or 0, -(c["reviews"] or 0)), reverse=True)
    return out[:limit]
