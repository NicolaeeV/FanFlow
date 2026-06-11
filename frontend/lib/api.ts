const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080";

const sleep = (ms: number) => new Promise(res => setTimeout(res, ms));

// Resilient fetch: on first load the backend may still be warming up (cold Atlas
// connect / cache fill), so a transient network failure or 5xx is RETRIED with backoff
// instead of dead-ending the chat with "couldn't reach the guide". Each attempt gets a
// generous 30s timeout — the deterministic guide can take several seconds on a cold cache.
async function apiFetch(path: string, init?: RequestInit, retries = 3): Promise<Response> {
  let lastErr: unknown;
  for (let i = 0; i <= retries; i++) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 30000);
      try {
        const r = await fetch(`${BASE}${path}`, { ...init, signal: ctrl.signal });
        if (!r.ok && r.status >= 500 && i < retries) { await sleep(800 * (i + 1)); continue; }
        return r;
      } finally { clearTimeout(timer); }
    } catch (e) {
      lastErr = e;
      if (i < retries) { await sleep(800 * (i + 1)); continue; }
    }
  }
  throw lastErr;
}

export async function getEvents(city = "bay_area") {
  const r = await apiFetch(`/api/events?city=${city}`);
  return (await r.json()).events as any[];
}

export async function getBusinesses(neighborhood = "") {
  const q = neighborhood ? `?neighborhood=${neighborhood}` : "";
  const r = await fetch(`${BASE}/api/businesses${q}`);
  return (await r.json()).businesses as any[];
}

export async function getMarketMix(eventId: string) {
  const r = await fetch(`${BASE}/api/source-market-mix?event_id=${eventId}`);
  return await r.json();
}

export async function generatePlan(business_id: string, event_id: string) {
  const r = await fetch(`${BASE}/api/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ business_id, event_id }),
  });
  return await r.json();
}

export async function askAgent(business_id: string, event_id: string, message: string) {
  const r = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ business_id, event_id, message }),
  });
  return await r.json();
}

export async function buildItinerary(event_id: string, start: string, time_budget_hours: number) {
  const r = await fetch(`${BASE}/api/itinerary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_id, start, time_budget_hours }),
  });
  return await r.json();
}

export async function visitorRecommend(query: string, event_id = "") {
  const r = await fetch(`${BASE}/api/visitor/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, event_id }),
  });
  return await r.json();
}

export async function visitorChat(query: string, event_id = "", answers: Record<string, string> = {},
                                  history: string[] = [], rejected_ids: string[] = []) {
  const r = await apiFetch(`/api/visitor/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, event_id, answers, history, rejected_ids }),
  });
  return await r.json();
}

export async function routeLocalFavorites(query: string, neighborhood = "", event_id = "") {
  const r = await fetch(`${BASE}/api/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, neighborhood, event_id }),
  });
  return await r.json();
}

export async function approvePlan(plan_id: string) {
  const r = await fetch(`${BASE}/api/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_id }),
  });
  return await r.json();
}

export async function semanticSearch(query: string, neighborhood = "") {
  const r = await fetch(`${BASE}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, neighborhood }),
  });
  return await r.json();
}

// ── Google Growth Coach ───────────────────────────────────────────────────────
export async function getGrowthCoach(business_id: string, event_id: string) {
  const r = await fetch(`${BASE}/api/growth/coach?business_id=${business_id}&event_id=${event_id}`);
  return await r.json();
}

export async function respondToReview(business_id: string, review_text: string, rating: number | null = null) {
  const r = await fetch(`${BASE}/api/growth/reviews/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ business_id, review_text, rating }),
  });
  return await r.json();
}

// ── Business Intelligence + rankings ──────────────────────────────────────────
export async function getRankedBusinesses(event_id: string, neighborhood = "", limit = 30, kind = "") {
  const p = new URLSearchParams({ event_id, neighborhood, limit: String(limit), kind });
  const r = await fetch(`${BASE}/api/businesses/ranked?${p}`);
  return await r.json();
}

export async function getHiddenGems(event_id: string, neighborhood = "", limit = 20) {
  const p = new URLSearchParams({ event_id, neighborhood, limit: String(limit) });
  const r = await fetch(`${BASE}/api/businesses/hidden-gems?${p}`);
  return await r.json();
}

export async function getBusinessIntel(business_id: string, event_id: string) {
  const r = await fetch(`${BASE}/api/business/intel?business_id=${business_id}&event_id=${event_id}`);
  return await r.json();
}
