"""Google crawler IP verification (security / log-trust only).

Pattern from the google-ip-list project: Google publishes its crawler IP ranges as JSON
(`prefixes: [{ipv4Prefix|ipv6Prefix}]`) at developers.google.com/static/crawling/ipranges/*.
A request claiming `Googlebot` in its User-Agent is ONLY trustworthy if its IP falls in
those official ranges — UA strings are trivially spoofable.

USE: verify webhook/log/SEO-tool requests and access logs. **Never** use this to identify,
personalize, or profile end users. Refresh ranges from Google periodically.
"""
from __future__ import annotations
import ipaddress

# Official source URLs (load_google_ip_ranges fetches/caches these in production).
GOOGLE_IP_RANGE_URLS = [
    "https://developers.google.com/static/crawling/ipranges/common-crawlers.json",
    "https://developers.google.com/static/crawling/ipranges/special-crawlers.json",
    "https://developers.google.com/static/crawling/ipranges/user-triggered-fetchers.json",
]

# Small seeded subset of REAL Googlebot prefixes (from Google's published list) so the
# verifier works offline/in tests. Production should refresh from the URLs above.
_SEED_PREFIXES = [
    "66.249.64.0/19", "66.249.79.0/24", "34.100.182.96/28", "35.247.243.0/24",
    "2001:4860:4801:10::/64", "2001:4860:4801:11::/64", "2001:4860:4801:2000::/64",
]


def load_google_ip_ranges(json_blobs: list[dict] | None = None) -> list:
    """Parse Google's crawler-range JSON into ip_network objects.

    Pass the fetched JSON blobs (each {'prefixes': [{'ipv4Prefix'|'ipv6Prefix': cidr}]});
    with none provided, falls back to the seeded subset. Never fabricates ranges.
    """
    nets, prefixes = [], []
    if json_blobs:
        for blob in json_blobs:
            for p in (blob or {}).get("prefixes", []):
                cidr = p.get("ipv4Prefix") or p.get("ipv6Prefix")
                if cidr:
                    prefixes.append(cidr)
    else:
        prefixes = _SEED_PREFIXES
    for cidr in prefixes:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue  # skip malformed entries, never guess
    return nets


def refresh_from_google(timeout: int = 8) -> list:
    """Fetch Google's official crawler-range JSON and parse to ip_networks.

    Falls back to the seeded subset on any network/parse error (never crashes, never guesses).
    """
    blobs = []
    try:
        import httpx
        for url in GOOGLE_IP_RANGE_URLS:
            try:
                r = httpx.get(url, timeout=timeout)
                r.raise_for_status()
                blobs.append(r.json())
            except Exception:
                continue
    except Exception:
        return load_google_ip_ranges()
    return load_google_ip_ranges(blobs) if blobs else load_google_ip_ranges()


def is_google_crawler_ip(ip: str, ranges: list | None = None) -> bool:
    ranges = ranges if ranges is not None else load_google_ip_ranges()
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr.version == net.version and addr in net for net in ranges)


def verify_googlebot_request(ip: str, user_agent: str, ranges: list | None = None) -> dict:
    """Trust a 'Googlebot' claim ONLY if the IP is in Google's official ranges."""
    claims_googlebot = "googlebot" in (user_agent or "").lower()
    ip_ok = is_google_crawler_ip(ip, ranges)
    verified = claims_googlebot and ip_ok
    if claims_googlebot and not ip_ok:
        reason = "REJECTED: User-Agent claims Googlebot but IP is not in Google's verified ranges (spoof)."
    elif not claims_googlebot:
        reason = "Not a Googlebot claim."
    else:
        reason = "Verified Googlebot (UA claim + IP in official ranges)."
    return {"verified_googlebot": verified, "claims_googlebot": claims_googlebot,
            "ip_in_google_ranges": ip_ok, "reason": reason,
            "note": "Security/log trust only — never used to identify or personalize users."}
