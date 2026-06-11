# FanFlow — MatchDay Local

**A World Cup 2026 food guide for fans, and a demand‑intelligence agent for the small businesses that feed them.**

Built for the Google Cloud Rapid Agent Hackathon · Partner track: MongoDB · Demo venue: **Levi's Stadium, Santa Clara (SF Bay Area)**.

FanFlow has two surfaces over one shared, verified data core:

- **Visitor guide** (`/api/visitor/chat`) — a fast, multilingual chat that helps a fan find a real place to eat near the stadium: by cuisine, dish, diet (vegetarian / vegan / gluten‑free / **halal** / kosher / allergies), budget, group size, and match‑day timing — with route, open hours, crowd, and the source behind every pick.
- **Owner agent** (`/api/chat`) — a Gemini 3 + Google ADK agent with the **MongoDB MCP** server as a partner integration. It reasons over a demand model, calls live tools, and produces an owner‑approvable match‑day action plan (hours, staffing, inventory, Google Business Profile updates, a Google Ads plan, multilingual copy, a revenue‑lift range).

---

## Why not just Google Maps?

Google Maps ranks local results largely by **prominence** — which is heavily **review‑count** driven (Google dropped Bayesian smoothing in 2017). So a chain with thousands of reviews structurally outranks a beloved neighborhood spot with 34 reviews, *even at a worse rating*. FanFlow re‑ranks for **"local and good," not "most reviewed."**

It trusts a rating **in proportion to the evidence behind it** — Bayesian shrinkage toward the **per‑category area mean** (measured from the live dataset; global mean 4.2), weight 30:

| Place | Category mean | Google avg | Reviews | FanFlow score | Result |
|---|---|---|---|---|---|
| Taco Bell | 3.8 (fast food) | 3.7 | 2,500 | 3.70 | chain → behind locals |
| Chipotle | 3.8 (fast food) | 3.9 | 1,800 | 3.90 | chain → behind locals |
| **Mom‑and‑pop taqueria** | 4.3 (mexican) | 4.8 | 34 | **4.57** | **leads** |
| **Beloved local** | 4.3 (mexican) | 4.7 | 210 | **4.65** | **leads** |
| Thin 5‑star | 4.3 (mexican) | 5.0 | 6 | 4.42 | not over‑trusted |

The 34‑review taqueria beats Taco Bell — and a thin 5.0★/6‑review place does **not** top a proven 4.8★/34. Judging each place against its *own* category's norm (a fast‑food 3.8, a taqueria 4.3) stops a flat global prior from quietly flattering a weak chain. Four things Maps doesn't do:

- **Per‑category Bayesian rating** — neither buries a low‑review gem nor over‑trusts a thin 5‑star, and measures each place against its *own* category's mean.
- **Community‑locality signal** — *how the neighborhood cherishes a place*: independence, being loved **above its category average**, real review‑snippet sentiment, and the under‑reviewed‑yet‑beloved (hidden‑gem) pattern.
- **Locality boost, not a chain cliff** — independents get a community‑locality lift; a chain takes a **gentle** derank, **not** a burial, so a genuinely good chain still surfaces on merit (it just sits below the cherished locals). We *enhance locality without diminishing good chains*.
- **Hidden‑gem boost** — well‑rated, locally‑loved, *under‑reviewed* spots get surfaced, not buried.

Plus match‑day reasoning Maps has no concept of (route vs. kickoff, halftime/post‑rush timing, open‑at‑the‑asked‑hour, halal/diet as hard filters, multilingual replies) — and an **owner side** that helps the small shop get *found* when the crowd searches.

---

## Coverage area

FanFlow covers the **South Bay around Levi's Stadium** — not the whole Bay Area.

| Trip | Radius from Levi's Stadium | Includes |
|------|---------------------------|----------|
| **Match day** (pre‑/post‑match) | **~11 mi / ~18 km** (cuisine matches pulled to ~15 mi / 25 km) | Santa Clara, San José (Downtown, Santana Row, Japantown, SAP Center), Sunnyvale, Mountain View, Cupertino, Milpitas, Campbell, Palo Alto |
| **Next‑day / exploration** | **~50 mi / ~80 km** | the wider South Bay & Peninsula |

Ask about somewhere outside that — San Francisco ("the city"), Oakland, Berkeley, Napa, Santa Cruz, Monterey, Gilroy, or anywhere farther — and it tells you plainly that it's outside the area and offers local options instead, rather than passing off a stadium‑area spot as if it were there. A clear local anchor ("walkable from Levi's", "near Santana Row") always wins.

---

## How the visitor guide works

A fan types naturally — English, Spanish, Portuguese, Arabic, Spanglish, slang, typos, even emoji or a country flag (🇲🇽 → Mexican, 🇸🇦 → halal/Mediterranean) — and gets up to three picks, each answering the questions that actually matter on a tight match clock:

- **Does it match what I asked?** Cuisine and dish routing (tacos, sushi, pho, injera, ceviche, banh mi, …), diet and **halal/kosher** as real filters, budget, party size.
- **Can I get there and back in time?** Route and traffic vs. kickoff, transit/walking/driving, pre‑match vs. halftime vs. the post‑match rush.
- **Is it open?** Hours checked against the asked time (it won't send you somewhere closed at 2 a.m.).
- **Is it any good — and real?** Ratings are bias‑corrected (a beloved 4.7★ with 2,000 reviews isn't buried under a thin 5★), and **every recommendation is a real, verified place** — with the source and freshness shown.

### How a place is described

A place is described by its **food and character**, never by the people behind it:

- **What kind of food** it serves — the cuisine and signature dishes (al pastor, ceviche, banh mi).
- **The food's story** — regional style, tradition, what makes the cooking distinctive.
- **How local it is** — independent vs. chain, a neighborhood favorite, a hidden gem, how long it's been around.

The visitor's language preference comes only from the words they use or aggregate match context — used to reply in their language, nothing more.

---

## The owner agent (the "beyond‑chat" artifact)

`POST /api/chat` runs a Gemini 3 `LlmAgent` (Google ADK) with **28 function tools + the MongoDB Atlas MCP server** (read‑only) as the required partner integration. Given a business + a match, it chains tools — schedule → source‑market mix → foot‑traffic forecast → inventory/ads/profile builders → MongoDB reads — into an approvable plan:

- Hourly **foot‑traffic forecast** (p10/p50/p90) for the surge window.
- **Staffing, inventory, and hours** tuned to that forecast.
- **Google Business Profile** updates and a **Google Ads** keyword plan to help the spot get found when the crowd searches — without ever claiming a guaranteed or buyable rank.
- **Multilingual** landing/post copy for the visiting fan base.
- A **revenue‑lift range** with explicit, honest risk controls.

`GET /api/agent/status` reports readiness (`adk_built`, `mongodb_mcp_attached`, `model_credential`, `ready_for_live_agent`).

---

## Architecture

```
Frontend (Next.js 14, /fan)
        │
        ▼
FastAPI (backend/app/server.py, :8080)
   ├── /api/visitor/chat → plan_visitor_chat   (deterministic, ~1.5s, no model key needed)
   └── /api/chat         → Gemini 3 + ADK agent + MongoDB MCP  (the agentic artifact)
        │
        ▼
Data: MongoDB Atlas (businesses, events, reviews, plans) + Google Maps Platform (Places, Routes, Geocoding)
   • Degrades to a bundled JSON seed if Atlas is briefly unreachable — the chat keeps answering.
```

**Stack:** Python 3.12 / FastAPI · Google ADK 2.x + Gemini 3 · MongoDB Atlas + `mongodb-mcp-server` (Node 18+) · Google Maps Platform · Next.js 14 frontend.

---

## Quickstart

```bash
# 1) Backend
cd backend
python -m venv .venv && . .venv/Scripts/activate      # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
cp .env.example .env                                   # add MONGODB_URI + GOOGLE_MAPS_API_KEY
python -m uvicorn app.server:app --port 8080           # warms caches on startup (~20s)

# 2) Frontend
cd ../frontend
npm install && npm run dev                             # http://localhost:3000/fan
```

**Notes**
- The **visitor guide works with no model key** (it's deterministic). The **owner agent** needs a Gemini credential — `GOOGLE_API_KEY` (AI Studio) or `GOOGLE_CLOUD_PROJECT` + Vertex ADC — and `GEMINI_MODEL` (default `gemini-3.1-flash-lite`, reliable on the free tier).
- The agent's MongoDB MCP runs via `npx mongodb-mcp-server`, so the **owner‑agent path needs Node 18+** (`npm i -g mongodb-mcp-server` to pre‑cache). The fan app needs no extra Node.
- Credentials live in `backend/.env` (git‑ignored). Without `MONGODB_URI`/`GOOGLE_MAPS_API_KEY`, everything degrades to the bundled JSON seed so the demo still runs offline.

### Demo flow
1. Lead with the **fan app** (`/fan`) for responsiveness — try
   *"hola, comida cerca del estadio con mis niños, algo barato, antes del partido, en VTA"* → it replies in Spanish with a safe pick, a local gem, and a backup; then *"post match food near Levi's driving, 45 minutes before kickoff"* → it warns the plan risks missing kickoff and offers a faster local spot.
2. Then show **`/api/chat`** doing the multi‑tool + MongoDB‑MCP reasoning to build an owner action plan for **Mexico vs Saudi Arabia**.
3. Start the backend ~20s before judging so the prewarm completes.

---

## Tests

```bash
cd backend
python -m pytest tests/ -q       # ~650 tests, hermetic (no network needed)
python probe_chat.py             # adversarial probe harness across cuisine / language / location /
                                 # timing / dietary / abuse / unicode / scope categories
```

The suite is hermetic — `tests/conftest.py` blanks `MONGODB_URI`/`GOOGLE_MAPS_API_KEY` so tests run offline against the seed; the live app reads Atlas + Maps when `.env` is present.

---

## License

Apache 2.0 — see [LICENSE](./LICENSE).
