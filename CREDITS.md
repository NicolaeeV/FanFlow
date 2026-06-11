# Credits & Attribution

MatchDay Local adapts **patterns and concepts** from several open-source projects. We did
not copy their code; we re-implemented the ideas in our own Python/TypeScript for the
World Cup use case. Each is credited below. If any of these are reused more directly in
future, their original licenses will be honored and included here.

| Project | What we adapted | Where it lives here |
|---|---|---|
| **SmartTourister** (salil-gtm) | "Find best-rated places, then compute an optimal visit sequence" — nearest-neighbor route over rated places (`shortestRoute`/`getShortest`) | `backend/app/tools/itinerary.py` (`_nearest_neighbor`, match-day route sequencing) |
| **Smart-Tourist-Guide** | "Ask the visitor interests + time available + location, then rank places and build a schedule for the time window" | `backend/app/tools/itinerary.py` (intent + time-budget + start → selected/sequenced stops) |
| **Agent-Reach** | "Give the agent eyes on the public internet" — multi-source discovery (Reddit/X/web/etc.) | `backend/app/tools/discovery.py` (fan-venue discovery ingestor with source + confidence) |
| **last30days-skill** (mvanhorn, MIT) | "Research what's actually risen recently" — recent posts/engagement deltas across sources | `backend/app/tools/recent_signals.py` (rising query clusters + new watch parties, ~30-day window) |
| **Personal_AI_Infrastructure** | Modular agent/memory/tool structure | Overall agent/tool modularity (`backend/app/agent.py`, `tools/` package) |
| **busy-hours** | **Output SHAPE only** (`week:[{day,hours:[{hour,percentage}]}], now`) for a crowd model | `backend/app/tools/capacity.py` — computed from our own forecast. ⚠️ **REJECTED** its Google Popular Times HTML scraping (`extract_data`/`eval`) — Maps-ToS risk; we never scrape it. |
| **google-ip-list** | Concept + official JSON format (`prefixes:[{ipv4Prefix\|ipv6Prefix}]` from Google's crawler-range endpoints) | `backend/app/tools/google_crawler_security.py` — verify Googlebot by IP, reject UA-only spoofs. Security/log-trust only; **never** used to identify/personalize users. |

See **[docs/REUSE.md](docs/REUSE.md)** for the detailed mapping and the public sources used
to seed Bay Area fan venues and trip-length assumptions.

MatchDay Local itself is licensed under Apache-2.0 (see [LICENSE](LICENSE)).
