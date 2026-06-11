"use client";
import { useEffect, useState, useRef } from "react";
import {
  getEvents, getBusinesses, getMarketMix,
  generatePlan, approvePlan, askAgent,
  visitorChat, buildItinerary,
  getGrowthCoach, respondToReview,
  getRankedBusinesses, getHiddenGems, getBusinessIntel,
} from "../lib/api";

// ── Icons (inline SVG helpers) ──────────────────────────────────────────────
const Icon = ({ d, size = 16, color = "currentColor" }: { d: string; size?: number; color?: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const ICONS = {
  home:     "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z M9 22V12h6v10",
  chart:    "M18 20V10 M12 20V4 M6 20v-6",
  eye:      "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z M12 12m-3 0a3 3 0 106 0 3 3 0 00-6 0",
  plan:     "M9 11l3 3L22 4 M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11",
  map:      "M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z M12 10m-3 0a3 3 0 106 0 3 3 0 00-6 0",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z",
  shield:   "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  bell:     "M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9 M13.73 21a2 2 0 01-3.46 0",
  help:     "M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3 M12 17h.01",
  chevron:  "M9 18l6-6-6-6",
  star:     "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z",
  camera:   "M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z M12 17a4 4 0 100-8 4 4 0 000 8",
  link:     "M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71 M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71",
  clock:    "M12 2a10 10 0 100 20A10 10 0 0012 2z M12 6v6l4 2",
  globe:    "M12 2a10 10 0 100 20A10 10 0 0012 2z M2 12h20 M12 2a15.3 15.3 0 010 20 M12 2a15.3 15.3 0 000 20",
  trending: "M23 6l-9.5 9.5-5-5L1 18",
  dollar:   "M12 1v22 M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6",
  users:    "M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2 M9 7a4 4 0 100 8 4 4 0 000-8z M23 21v-2a4 4 0 00-3-3.87 M16 3.13a4 4 0 010 7.75",
  spark:    "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  refresh:  "M1 4v6h6 M23 20v-6h-6 M20.49 9A9 9 0 005.64 5.64L1 10 M23 14l-4.64 4.36A9 9 0 013.51 15",
};

// ── Demand forecast data ─────────────────────────────────────────────────────
const FORECAST_HOURS = [
  { h: "12 PM", lift: 8 },
  { h: "1 PM",  lift: 14 },
  { h: "2 PM",  lift: 22 },
  { h: "3 PM",  lift: 30 },
  { h: "4 PM",  lift: 45 },
  { h: "5 PM",  lift: 70, peak: true },
  { h: "6 PM",  lift: 65 },
  { h: "7 PM",  lift: 55 },
  { h: "8 PM",  lift: 40 },
  { h: "9 PM",  lift: 22 },
  { h: "10 PM", lift: 10 },
];

// ── DemandChart ──────────────────────────────────────────────────────────────
function DemandChart({ matchName }: { matchName: string }) {
  const W = 560, H = 180, padT = 16, padB = 36, padL = 36, padR = 16;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const maxLift = 80;
  const barW = Math.floor(innerW / FORECAST_HOURS.length) - 6;

  const yPct = (v: number) => padT + innerH - (v / maxLift) * innerH;
  const xBar = (i: number) => padL + i * (innerW / FORECAST_HOURS.length) + 3;

  const gridLines = [0, 25, 50, 75];

  return (
    <div className="chart-wrap">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Expected visitor demand vs a normal Saturday
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--muted)" }}>
          <span style={{ width: 10, height: 10, borderRadius: 3, background: "var(--blue)", display: "inline-block" }} />
          {matchName}
        </div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block", minWidth: 340 }}>
          {/* grid lines */}
          {gridLines.map(g => (
            <g key={g}>
              <line
                x1={padL} y1={yPct(g)} x2={W - padR} y2={yPct(g)}
                stroke="var(--border)" strokeWidth={g === 0 ? 1.5 : 1}
                strokeDasharray={g === 0 ? "none" : "4 4"}
              />
              {g > 0 && (
                <text x={padL - 6} y={yPct(g) + 4} textAnchor="end" fontSize={9} fill="var(--faint)">
                  +{g}%
                </text>
              )}
            </g>
          ))}
          {/* baseline label */}
          <text x={W - padR + 4} y={yPct(0) + 4} fontSize={9} fill="var(--muted)" textAnchor="start">Baseline</text>

          {/* bars */}
          {FORECAST_HOURS.map((d, i) => {
            const bh = (d.lift / maxLift) * innerH;
            const by = padT + innerH - bh;
            const bx = xBar(i);
            return (
              <g key={d.h}>
                <rect
                  x={bx} y={by} width={barW} height={bh}
                  rx={4}
                  fill={d.peak ? "var(--blue)" : "var(--blue-mid)"}
                  opacity={d.peak ? 1 : 0.75}
                />
                {d.peak && (
                  <rect x={bx - 2} y={by - 2} width={barW + 4} height={bh + 2} rx={5}
                    fill="none" stroke="var(--blue)" strokeWidth={1.5} opacity={0.4} />
                )}
                <text
                  x={bx + barW / 2} y={H - padB + 14}
                  textAnchor="middle" fontSize={9.5}
                  fill={d.peak ? "var(--blue)" : "var(--muted)"}
                  fontWeight={d.peak ? "700" : "400"}
                >
                  {d.h}
                </text>
                {d.peak && (
                  <text x={bx + barW / 2} y={by - 5} textAnchor="middle" fontSize={9} fill="var(--blue)" fontWeight="700">
                    Peak
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ── ScoreGauge ───────────────────────────────────────────────────────────────
function ScoreGauge({ score }: { score: number }) {
  const r = 36, cx = 45, cy = 45, circumference = 2 * Math.PI * r;
  const pct = Math.min(score / 100, 1);
  const dash = circumference * pct;
  const gap = circumference - dash;
  return (
    <svg className="score-circle" viewBox="0 0 90 90">
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--border)" strokeWidth={7} />
      <circle cx={cx} cy={cy} r={r} fill="none"
        stroke={score >= 70 ? "var(--teal)" : score >= 50 ? "var(--amber)" : "var(--red)"}
        strokeWidth={7} strokeLinecap="round"
        strokeDasharray={`${dash} ${gap}`}
        transform={`rotate(-90 ${cx} ${cy})`}
      />
      <text x={cx} y={cy + 5} textAnchor="middle" fontSize={18} fontWeight="800" fill="var(--text)">{score}</text>
    </svg>
  );
}

// ── Sidebar ──────────────────────────────────────────────────────────────────
const NAV_ITEMS = [
  { id: "overview",  label: "Overview",          icon: "home"     },
  { id: "forecast",  label: "Match Forecast",    icon: "chart"    },
  { id: "businesses",label: "Businesses",        icon: "users"    },
  { id: "plan",      label: "Action Plan",       icon: "plan"     },
  { id: "growth",    label: "Google Growth Coach", icon: "trending" },
  { id: "neighborhoods", label: "Neighborhoods", icon: "map"      },
  { id: "settings",  label: "Settings",          icon: "settings" },
];

function Sidebar({ active, onNav }: { active: string; onNav: (id: string) => void }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">⚽</div>
        <div>
          <div className="sidebar-logo-text">FanFlow AI</div>
          <div className="sidebar-logo-sub">Matchday intelligence</div>
        </div>
      </div>
      <nav className="sidebar-nav">
        <div className="nav-section-label">Navigation</div>
        {NAV_ITEMS.map(item => (
          <button
            key={item.id}
            className={`nav-item${active === item.id ? " active" : ""}`}
            onClick={() => onNav(item.id)}
          >
            <Icon d={ICONS[item.icon as keyof typeof ICONS]} size={15} />
            {item.label}
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-footer-badge">
          <Icon d={ICONS.shield} size={13} />
          Safe. Private. Powerful.
        </div>
        We never infer ethnicity or individual nationality.
      </div>
    </aside>
  );
}

// ── VisitorMix card ──────────────────────────────────────────────────────────
function VisitorMixCard({ mix }: { mix: any }) {
  if (!mix || mix.error) return null;
  const countries = mix.country_mix || mix.top_markets || [];
  const langs = mix.language_mix || mix.languages_spoken?.map((l: string) => ({ lang: l, share: 0.2 })) || [];
  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-title">
        <Icon d={ICONS.users} size={15} color="var(--blue)" />
        Who's likely around
        <span style={{ marginLeft: "auto", fontSize: 11, background: "var(--teal-lt)", color: "var(--teal)", padding: "2px 8px", borderRadius: 999, fontWeight: 600, border: "1px solid var(--teal-mid)" }}>
          aggregate only
        </span>
      </div>
      <div className="card-subtitle">Privacy-safe area signals. No individual data.</div>

      <div style={{ marginBottom: 12 }}>
        <div className="mix-label" style={{ marginBottom: 6 }}>Country mix (top)</div>
        <div className="mix-row">
          {countries.slice(0, 4).map((c: any) => (
            <span key={c.country || c.lang} className={`mix-chip ${c.share >= 0.3 || c.share_pct >= 30 ? "blue" : "gray"}`}>
              {(c.country || c.lang || "").toUpperCase()}&nbsp;
              {c.share_pct != null ? c.share_pct : Math.round((c.share || 0) * 100)}%
            </span>
          ))}
        </div>
      </div>

      <div className="card-divider" />

      <div>
        <div className="mix-label" style={{ marginBottom: 6 }}>Language mix (operational)</div>
        <div className="mix-row">
          {langs.slice(0, 4).map((l: any) => (
            <span key={l.lang} className="mix-chip teal">
              {(l.lang || "").toUpperCase()}&nbsp;{Math.round((l.share || 0) * 100)}%
            </span>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 12, fontSize: 11, color: "var(--muted)", display: "flex", gap: 5, alignItems: "center" }}>
        <Icon d={ICONS.shield} size={11} color="var(--teal)" />
        Privacy-safe: aggregated area signals. No individual data.
      </div>
    </div>
  );
}

// ── VisibilityCard ───────────────────────────────────────────────────────────
function VisibilityCard({ plan }: { plan: any }) {
  const score = plan?.visibility_score ?? 59.9;
  const components = plan?.visibility_components || {};
  const fixes = plan?.visibility_fixes || [
    "Add a menu link to your Google Business Profile",
    "Add a reservation or order link",
    "Add 10+ recent, high-quality photos",
    "Add es/ar menu + profile description",
    "Encourage more recent rating reviews",
  ];
  return (
    <div className="card">
      <div className="card-title"><Icon d={ICONS.eye} size={15} color="var(--blue)" />Search visibility score</div>
      <div className="card-subtitle">Improves conversion readiness and matchday discoverability.</div>
      <div className="score-gauge-wrap">
        <ScoreGauge score={score} />
        <div className="score-info">
          <div><span className="score-value">{score}</span><span className="score-max">/100</span></div>
          <div className="score-status">{score >= 70 ? "Looking good" : score >= 50 ? "Room to grow" : "Needs attention"}</div>
          <div className="score-desc">
            {score >= 70
              ? "Strong visibility. Keep your profile fresh to maintain ranking."
              : "You're visible, but key optimizations can unlock more matchday demand."}
          </div>
        </div>
      </div>

      {Object.keys(components).length > 0 && (
        <div style={{ marginBottom: 14 }}>
          {Object.entries(components).map(([k, v]: any) => (
            <div key={k} style={{ marginBottom: 7 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--muted)", marginBottom: 3 }}>
                <span style={{ textTransform: "capitalize" }}>{k.replace(/_/g, " ")}</span>
                <span style={{ fontWeight: 600, color: "var(--text2)" }}>{Math.round(v * 100)}%</span>
              </div>
              <div style={{ height: 5, background: "var(--surface2)", borderRadius: 3, overflow: "hidden", border: "1px solid var(--border)" }}>
                <div style={{ height: "100%", width: `${v * 100}%`, background: v >= 0.7 ? "var(--teal)" : v >= 0.5 ? "var(--blue)" : "var(--amber)", borderRadius: 3 }} />
              </div>
            </div>
          ))}
          <div className="card-divider" />
        </div>
      )}

      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text2)", marginBottom: 8 }}>Top controllable fixes</div>
      <ul className="fix-list">
        {fixes.slice(0, 5).map((f: string, i: number) => (
          <li key={i} className="fix-item">
            <span className="fix-dot" />
            <span style={{ flex: 1 }}>{f}</span>
            <span className="fix-chevron">›</span>
          </li>
        ))}
      </ul>
      <button className="section-link">See all visibility insights →</button>
    </div>
  );
}

// ── ActionPlanCard ───────────────────────────────────────────────────────────
const ACTIONS = [
  { icon: "camera", name: "Add 10+ recent, high-quality photos", reason: "Boosts clicks and conversions", priority: "High" },
  { icon: "link",   name: "Add a reservation or order link",    reason: "Reduces friction, increases bookings", priority: "High" },
  { icon: "clock",  name: "Update busy-hour & matchday hours",  reason: "Set expectations, capture more demand", priority: "Medium" },
  { icon: "globe",  name: "Add es/ar menu + profile description",reason: "Aggregate demand shows es, ar opportunity", priority: "Medium" },
  { icon: "star",   name: "Encourage more recent rating reviews",reason: "Build trust, improve local rank", priority: "Low" },
];

function ActionPlanCard({ plan }: { plan: any }) {
  const steps = plan?.steps || [];
  const actions = steps.length > 0
    ? steps.slice(0, 5).map((s: string, i: number) => ({
        icon: ACTIONS[i % ACTIONS.length].icon,
        name: s, reason: "", priority: i < 2 ? "High" : i < 4 ? "Medium" : "Low",
      }))
    : ACTIONS;

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <div className="card-title" style={{ margin: 0 }}>
          <Icon d={ICONS.plan} size={15} color="var(--blue)" />
          Recommended actions
        </div>
        {plan?.status && (
          <span style={{
            fontSize: 10.5, fontWeight: 700, padding: "3px 8px", borderRadius: 999,
            background: plan.status === "approved" ? "var(--green-lt)" : "var(--amber-lt)",
            color: plan.status === "approved" ? "var(--green)" : "var(--amber)",
            border: `1px solid ${plan.status === "approved" ? "#bbf7d0" : "#fde68a"}`,
            textTransform: "uppercase" as const, letterSpacing: ".04em",
          }}>
            {plan.status === "approved" ? "Approved" : "Draft"}
          </span>
        )}
      </div>
      <div className="card-subtitle">Prioritised by matchday impact. Review before publishing.</div>

      <div className="action-list">
        {actions.map((a: any, i: number) => (
          <div key={i} className="action-item">
            <div className="action-icon-wrap">{
              a.icon === "camera" ? "📷" : a.icon === "link" ? "🔗" :
              a.icon === "clock" ? "🕐" : a.icon === "globe" ? "🌐" : "⭐"
            }</div>
            <div className="action-text">
              <div className="action-name">{a.name}</div>
              {a.reason && <div className="action-reason">{a.reason}</div>}
            </div>
            <span className={`badge-priority badge-${a.priority.toLowerCase()}`}>{a.priority}</span>
            <span className="action-chevron">›</span>
          </div>
        ))}
      </div>
      <button className="section-link">View full action plan →</button>
    </div>
  );
}

// ── MultilingualCard ─────────────────────────────────────────────────────────
function MultilingualCard({ plan }: { plan: any }) {
  const copy = plan?.landing_copy || {
    en: "Open late for the match — fast service, group tables, walk from the stadium.",
    es: "Abierto hasta tarde para el partido — servicio rápido, mesas para grupos, a poca distancia del estadio.",
    ar: "مفتوح حتى وقت متأخر لمباراة كأس العالم — خدمة سريعة، طاولات للمجموعات، على بعد دقائق من الملعب.",
  };
  const name = plan?.business_name || "";
  const rows = [
    { lang: "EN", text: `${name ? name + ": " : ""}${copy.en || copy.EN || ""}`, rtl: false },
    { lang: "ES", text: `${name ? name + ": " : ""}${copy.es || copy.ES || ""}`, rtl: false },
    { lang: "AR", text: copy.ar || copy.AR || "مفتوح حتى وقت متأخر لمباراة كأس العالم — خدمة سريعة، طاولات للمجموعات، على بعد دقائق من الملعب.", rtl: true },
  ];
  return (
    <div className="card">
      <div className="card-title"><Icon d={ICONS.globe} size={15} color="var(--blue)" />Multilingual copy</div>
      <div className="card-subtitle">Operational marketing copy — language targeting, not identity targeting.</div>
      <div className="lang-list">
        {rows.map(r => r.text.trim() && (
          <div key={r.lang} className="lang-row">
            <span className={`lang-badge${r.lang === "AR" ? " ar" : ""}`}>{r.lang}</span>
            <span className={`lang-text${r.rtl ? " rtl" : ""}`}>{r.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── RisksCard ────────────────────────────────────────────────────────────────
function RisksCard({ plan }: { plan: any }) {
  const risks = plan?.risks?.length > 0 ? plan.risks : [
    "Stockout risk on top items if inventory is not raised",
    "Long waits / bad-review risk at peak hour",
    "Price-gouging risk — keep increases ethical (<20%, no essentials)",
  ];
  const policyOk = !plan?._policy_report || plan._policy_report.ok !== false;
  return (
    <div className="card">
      <div className="card-title"><Icon d={ICONS.shield} size={15} color="var(--amber)" />Risks &amp; guardrails</div>
      <div className="card-subtitle">Review before matchday. These are flagged automatically.</div>
      <div className="risk-list">
        {risks.slice(0, 5).map((r: string, i: number) => (
          <div key={i} className="risk-item">
            <span className="risk-dot amber" />
            <span>{r}</span>
          </div>
        ))}
      </div>
      {policyOk && (
        <div className="policy-check">
          <Icon d={ICONS.plan} size={13} />
          Policy check: passed
        </div>
      )}
    </div>
  );
}

// ── OwnerKPICards ────────────────────────────────────────────────────────────
function OwnerKPICards({ plan }: { plan: any }) {
  if (!plan) return null;
  const peak   = plan.forecast_peak?.hour ?? "—";
  const liftPct = plan.forecast_peak?.lift_pct ?? plan.forecast_peak?.lift_vs_normal_pct ?? 52;
  const revLow  = plan.revenue_lift_usd?.low ?? 790;
  const revHigh = plan.revenue_lift_usd?.high ?? 1235;
  const netLow  = plan.net_opportunity_usd?.low ?? null;
  const netHigh = plan.net_opportunity_usd?.high ?? null;
  const vis     = plan.visibility_score ?? 59.9;
  const conf    = Math.round((plan.confidence ?? 0.73) * 100);
  const langs   = (plan.languages || ["en", "es", "ar"]).slice(0, 3).join(" • ");

  let netLabel = "—";
  if (netLow != null && netHigh != null) {
    if (netLow < 0 && netHigh > 0) netLabel = `−$${Math.abs(netLow)} to +$${netHigh}`;
    else if (netLow < 0 && netHigh <= 0) netLabel = `−$${Math.abs(netLow)}–$${Math.abs(netHigh)}`;
    else netLabel = `$${netLow}–$${netHigh}`;
  }

  const cards = [
    { icon: "clock",    cls: "blue",  label: "Peak window",    value: peak, sub: `+${liftPct}% vs normal` },
    { icon: "dollar",   cls: "green", label: "Revenue lift",   value: `$${revLow}–$${revHigh}`, sub: "vs non-match day", valCls: "green" },
    { icon: "trending", cls: "amber", label: "Net opportunity", value: netLabel, sub: "after labor & stock risk" },
    { icon: "eye",      cls: "blue",  label: "Visibility score", value: `${vis}/100`, sub: vis >= 70 ? "Strong" : "Room to improve", highlighted: true },
    { icon: "shield",   cls: "teal",  label: "Confidence",     value: `${conf}%`, sub: conf >= 70 ? "Moderate-high" : "Moderate" },
    { icon: "globe",    cls: "teal",  label: "Languages",      value: langs.toUpperCase(), sub: "Live in your profile" },
  ];

  return (
    <div className="kpi-row">
      {cards.map((c, i) => (
        <div key={i} className={`kpi-card${c.highlighted ? " highlighted" : ""}`}>
          <div className="kpi-header">
            <div className={`kpi-icon ${c.cls}`}>
              <Icon d={ICONS[c.icon as keyof typeof ICONS]} size={14} color={`var(--${c.cls})`} />
            </div>
            <span className="kpi-label">{c.label}</span>
          </div>
          <div className={`kpi-value${c.valCls ? ` ${c.valCls}` : ""}`}>{c.value}</div>
          <div className="kpi-sub">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}

// ── AgentChat ────────────────────────────────────────────────────────────────
function AgentChat({ bizId, eventId }: { bizId: string; eventId: string }) {
  const [msgs, setMsgs] = useState<{ role: "user" | "agent"; text: string }[]>([]);
  const [input, setInput] = useState("What should I focus on for this match?");
  const [loading, setLoading] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  async function send() {
    if (!input.trim() || loading) return;
    const t = input.trim(); setInput(""); setLoading(true);
    setMsgs(m => [...m, { role: "user", text: t }]);
    try {
      const r = await askAgent(bizId, eventId, t);
      setMsgs(m => [...m, { role: "agent", text: r.reply || r.message || "…" }]);
    } catch { setMsgs(m => [...m, { role: "agent", text: "Could not reach agent." }]); }
    finally { setLoading(false); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, height: "100%" }}>
      <div className="chat-area" style={{ flex: 1 }}>
        {msgs.length === 0 && (
          <div style={{ color: "var(--muted)", fontSize: 12.5, padding: "8px 0" }}>
            Ask about staffing, inventory, visibility, or how to prepare for this match.
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>{m.text}</div>
        ))}
        {loading && <div className="chat-msg agent"><div className="spinner" /></div>}
        <div ref={bottom} />
      </div>
      <div className="chat-input-row">
        <input className="chat-input" value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()} placeholder="Ask the agent…" />
        <button className="btn-primary" onClick={send} disabled={loading || !input.trim()}
          style={{ padding: "10px 16px" }}>Send</button>
      </div>
    </div>
  );
}

// ── VisitorMode ──────────────────────────────────────────────────────────────
function VisitorMode({ eventId }: { eventId: string }) {
  const [msgs, setMsgs] = useState<{ role: "user" | "agent"; text: string }[]>([]);
  const [input, setInput] = useState("I'm visiting from Spain — where's a good local deli near Levi's?");
  const [loading, setLoading] = useState(false);
  const history = useRef<string[]>([]);
  const rejected = useRef<string[]>([]);
  const [startN, setStartN] = useState("downtown_san_jose");
  const [hours, setHours] = useState(3);
  const [itin, setItin] = useState<any>(null);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  async function send() {
    if (!input.trim() || loading) return;
    const t = input.trim(); setInput(""); setLoading(true);
    setMsgs(m => [...m, { role: "user", text: t }]);
    try {
      const r = await visitorChat(t, eventId, {}, history.current, rejected.current);
      let reply = "";
      if (r.follow_up || r.mode === "followup") { reply = r.message || r.follow_up; }
      else if (r.recommendations) {
        const slots = ["primary_fit", "local_alternative", "backup", "worth_trying", "soccer_pick"];
        const recs = slots.map((s: string) => r.recommendations?.[s]).filter(Boolean);
        if (recs.length) {
          const lead = r.message ? r.message + "\n\n" : "";
          reply = lead + recs.map((p: any) => {
            const why = p.why_matched || p.why_it_fits?.[0] || p.tagline || "";
            const tags = (p.matched_tags || []).slice(0, 4).join(" · ");
            const dist = p.route_note ? ` — ${p.route_note}` : "";
            return `**${p.name}**${tags ? ` _(${tags})_` : ""}${dist}\nWhy: ${why}`;
          }).join("\n\n");
          rejected.current = [...rejected.current, ...recs.map((p: any) => p.place_id || p._id).filter(Boolean)];
        } else { reply = r.message || "I couldn't find a verified match for that — try relaxing one thing (distance, timing, or budget)."; }
      } else { reply = r.message || JSON.stringify(r); }
      history.current = [...history.current, t];
      setMsgs(m => [...m, { role: "agent", text: reply }]);
    } catch { setMsgs(m => [...m, { role: "agent", text: "Could not reach agent." }]); }
    finally { setLoading(false); }
  }

  async function buildItin() {
    const r = await buildItinerary(eventId, startN, hours);
    setItin(r);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div className="card">
        <div className="card-title"><Icon d={ICONS.users} size={15} color="var(--blue)" />Find your home away from home</div>
        <div className="card-subtitle">Ask in any language. We use your request, not your identity, to recommend local spots.</div>
        <div className="chat-area">
          {msgs.length === 0 && (
            <div style={{ color: "var(--muted)", fontSize: 12.5 }}>
              Try: "best local deli near Levi's", "vegan options before the match", "kid-friendly and transit-easy"
            </div>
          )}
          {msgs.map((m, i) => <div key={i} className={`chat-msg ${m.role}`} style={{ whiteSpace: "pre-wrap" }}>{m.text}</div>)}
          {loading && <div className="chat-msg agent"><div className="spinner" /></div>}
          <div ref={bottom} />
        </div>
        <div className="chat-input-row" style={{ marginTop: 10 }}>
          <input className="chat-input" value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && send()} placeholder="Ask the local guide…" />
          <button className="btn-primary" onClick={send} disabled={loading || !input.trim()}
            style={{ padding: "10px 16px" }}>Ask</button>
        </div>
      </div>

      <div className="card">
        <div className="card-title"><Icon d={ICONS.map} size={15} color="var(--blue)" />Plan my match day</div>
        <div className="card-subtitle">Food → fan spot → route to the stadium.</div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 11, color: "var(--muted)", fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: ".04em" }}>Starting from</label>
            <select value={startN} onChange={e => setStartN(e.target.value)}
              style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 12px", fontSize: 13, color: "var(--text)", outline: "none" }}>
              <option value="downtown_san_jose">Downtown San José</option>
              <option value="santana_row">Santana Row</option>
              <option value="santa_clara_central">Santa Clara (near Levi's)</option>
              <option value="mountain_view_castro">Mountain View (Castro St)</option>
              <option value="sunnyvale_downtown">Sunnyvale</option>
            </select>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 11, color: "var(--muted)", fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: ".04em" }}>Time before kickoff</label>
            <select value={hours} onChange={e => setHours(Number(e.target.value))}
              style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 12px", fontSize: 13, color: "var(--text)", outline: "none" }}>
              <option value={2}>2 hours</option>
              <option value={3}>3 hours</option>
              <option value={4}>4 hours</option>
              <option value={6}>6 hours (off-day)</option>
            </select>
          </div>
          <button className="btn-primary" onClick={buildItin} style={{ alignSelf: "flex-end" }}>Build my plan</button>
        </div>
        {itin && (
          <ol className="itin-list">
            {(itin.itinerary || []).map((s: any, i: number) => (
              <li key={i} className="itin-item">
                <div className="itin-num">{i + 1}</div>
                <div className="itin-body">
                  <div className="itin-name">{s.name} <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 400 }}>({s.type?.replace(/_/g, " ")})</span></div>
                  <div className="itin-meta">+{s.travel_min_from_prev || 0} min travel{s.suggested_min ? ` · ${s.suggested_min} min stay` : ""}{s.why?.[0] ? ` · ${s.why[0]}` : ""}</div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

// ── Google Growth Coach view ─────────────────────────────────────────────────
function CopyBtn({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button className="copy-btn" onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200); }}>
      {done ? "Copied ✓" : "Copy"}
    </button>
  );
}

function GrowthBizMatchPicker({ businesses, events, bizId, setBizId, eventId, setEventId }: any) {
  const b = businesses.find((x: any) => x._id === bizId);
  const e = events.find((x: any) => x._id === eventId);
  return (
    <div className="control-row">
      <div className="selector-outer">
        <div className="selector-label">Business</div>
        <div className="selector" style={{ position: "relative" }}>
          <div className="selector-icon">🏪</div>
          <div className="selector-text">
            <div className="selector-main">{b?.name || "Select a business"}</div>
            <div className="selector-sub">{b ? `${b.category} · ${(b.neighborhood_id || "").replace(/_/g, " ")}` : ""}</div>
          </div>
          <span className="selector-chevron">▾</span>
          <select value={bizId} onChange={ev => setBizId(ev.target.value)}
            style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer", width: "100%", height: "100%" }}>
            {businesses.map((x: any) => <option key={x._id} value={x._id}>{x.name}</option>)}
          </select>
        </div>
      </div>
      <div className="control-divider" />
      <div className="selector-outer">
        <div className="selector-label">Match</div>
        <div className="selector" style={{ position: "relative" }}>
          <div className="selector-icon">⚽</div>
          <div className="selector-text">
            <div className="selector-main">{e ? `${e.team_home_name} vs ${e.team_away_name}` : "Select a match"}</div>
            <div className="selector-sub">{e ? (e.kickoff_local || "").slice(0, 10) : ""}</div>
          </div>
          <span className="selector-chevron">▾</span>
          <select value={eventId} onChange={ev => setEventId(ev.target.value)}
            style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer", width: "100%", height: "100%" }}>
            {events.map((x: any) => <option key={x._id} value={x._id}>{x.team_home_name} vs {x.team_away_name}</option>)}
          </select>
        </div>
      </div>
    </div>
  );
}

function GrowthCoachView({ businesses, events, bizId, setBizId, eventId, setEventId }: any) {
  const [coach, setCoach] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [reviewText, setReviewText] = useState("");
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewReply, setReviewReply] = useState<any>(null);

  useEffect(() => {
    if (!bizId || !eventId) return;
    setLoading(true); setCoach(null);
    getGrowthCoach(bizId, eventId).then(setCoach).catch(() => {}).finally(() => setLoading(false));
  }, [bizId, eventId]);

  async function onReply() {
    if (!reviewText.trim()) return;
    const r = await respondToReview(bizId, reviewText, reviewRating);
    setReviewReply(r);
  }

  const r = coach?.readiness;
  const score = r?.score ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* intro banner */}
      <div className="card" style={{ background: "var(--blue-lt)", borderColor: "var(--blue-mid)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 38, height: 38, borderRadius: 9, background: "linear-gradient(135deg,var(--blue),var(--teal))", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <Icon d={ICONS.trending} size={18} color="#fff" />
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15, color: "var(--text)" }}>Google Growth Coach</div>
            <div style={{ fontSize: 12.5, color: "var(--text2)" }}>
              FanFlow predicts the crowd surge — this is how your business gets <b>found, trusted, and chosen</b> on Google when that crowd searches.
            </div>
          </div>
        </div>
      </div>

      <GrowthBizMatchPicker {...{ businesses, events, bizId, setBizId, eventId, setEventId }} />

      {loading && <div className="card"><div className="empty-state"><div className="spinner" style={{ width: 28, height: 28, margin: "0 auto 12px" }} />Analyzing your Google presence…</div></div>}

      {coach && r && (<>
        {/* Readiness score + pillars */}
        <div className="two-col">
          <div className="card">
            <div className="card-title"><Icon d={ICONS.eye} size={15} color="var(--blue)" />Matchday Search Readiness Score</div>
            <div className="card-subtitle">{coach.business_name} · {coach.match} · source: {r.data_source === "google_places" ? "live Google data" : "seed"}</div>
            <div className="score-gauge-wrap">
              <ScoreGauge score={score} />
              <div className="score-info">
                <div><span className="score-value">{score}</span><span className="score-max">/100</span></div>
                <div className="score-status" style={{ color: score >= 75 ? "var(--teal)" : score >= 50 ? "var(--amber)" : "var(--red)" }}>{r.band}</div>
                <div className="score-desc">{r.disclaimer}</div>
              </div>
            </div>
            <div className="card-divider" />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
              {[["Relevance", r.pillars.relevance], ["Distance", r.pillars.distance], ["Prominence", r.pillars.prominence]].map(([k, v]) => (
                <div key={k} style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "var(--blue)", marginBottom: 3 }}>{k}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.4 }}>{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Top fixes this week */}
          <div className="card">
            <div className="card-title"><Icon d={ICONS.plan} size={15} color="var(--teal)" />Top fixes this week</div>
            <div className="card-subtitle">Owner-controllable — ranked by matchday impact.</div>
            <ul className="fix-list">
              {(r.controllable_fixes || []).slice(0, 6).map((f: any, i: number) => (
                <li key={i} className="fix-item">
                  <span className="fix-dot" style={{ background: "var(--teal)" }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: "var(--text)" }}>{f.action}</div>
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>{f.why}</div>
                  </div>
                </li>
              ))}
            </ul>
            {r.unknowns?.length > 0 && (
              <div style={{ marginTop: 10, fontSize: 11, color: "var(--muted)" }}>
                <b>Not enough signal:</b> {r.unknowns.map((u: any) => u.label).join(", ")} — we don't guess.
              </div>
            )}
          </div>
        </div>

        {/* Structural + GBP checklist */}
        <div className="two-col-wide">
          <div className="card">
            <div className="card-title"><Icon d={ICONS.shield} size={15} color="var(--blue)" />Google Business Profile checklist</div>
            <div className="card-subtitle">What Google and customers look for. Top fixes first.</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {(coach.gbp_audit?.checklist || []).map((c: any, i: number) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, padding: "4px 0" }}>
                  <span style={{ color: c.present ? "var(--green)" : "var(--faint)", fontWeight: 700 }}>{c.present ? "✓" : "○"}</span>
                  <span style={{ color: c.present ? "var(--text2)" : "var(--muted)", textTransform: "capitalize" }}>{c.field.replace(/_/g, " ")}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="card-title"><Icon d={ICONS.map} size={15} color="var(--muted)" />Structural factors</div>
            <div className="card-subtitle">You can't directly change these — but ads &amp; posts extend reach.</div>
            <div className="risk-list">
              {(r.structural_factors || []).map((s: any, i: number) => (
                <div key={i} className="risk-item">
                  <span className="risk-dot" style={{ background: "var(--muted)" }} />
                  <span><b>{s.factor}:</b> {s.reason}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Matchday posts */}
        <div className="card">
          <div className="card-title"><Icon d={ICONS.globe} size={15} color="var(--blue)" />Matchday Post generator</div>
          <div className="card-subtitle">Copy these into your Google Business Profile. {coach.posts?.note}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(coach.posts?.posts || []).map((p: any, i: number) => (
              <div key={i} className="action-item" style={{ alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700, fontSize: 13, color: "var(--text)" }}>{p.title}</div>
                  <div style={{ fontSize: 12, color: "var(--text2)" }}>{p.body}</div>
                  <span className="lang-badge" style={{ marginTop: 4, display: "inline-block" }}>CTA: {p.cta}</span>
                </div>
                <CopyBtn text={`${p.title}\n${p.body}`} />
              </div>
            ))}
            {(coach.posts?.language_variants || []).map((v: any, i: number) => (
              <div key={`lv${i}`} className="action-item" style={{ alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <span className={`lang-badge${v.lang === "ar" ? " ar" : ""}`}>{v.lang.toUpperCase()}</span>
                  <div style={{ fontSize: 12, color: "var(--text2)", marginTop: 4, direction: v.lang === "ar" ? "rtl" : "ltr" }}>{v.body}</div>
                </div>
                <CopyBtn text={v.body} />
              </div>
            ))}
          </div>
        </div>

        {/* Ads helper */}
        <div className="card">
          <div className="card-title"><Icon d={ICONS.spark} size={15} color="var(--blue)" />Google Ads helper <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--muted)", fontWeight: 400 }}>readiness, not guaranteed results</span></div>
          <div className="card-subtitle">Category: {coach.ads?.kind} · conversion focus: {coach.ads?.conversion_focus}</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <div>
              <div className="mix-label" style={{ marginBottom: 6 }}>Headline ideas</div>
              {(coach.ads?.headlines || []).map((h: string, i: number) => (
                <div key={i} style={{ fontSize: 12.5, padding: "4px 0", color: "var(--text2)" }}>• {h}</div>
              ))}
              <div className="mix-label" style={{ margin: "10px 0 6px" }}>Geo-targeting</div>
              <div className="mix-row">{(coach.ads?.geo_targeting || []).map((g: string, i: number) => <span key={i} className="mix-chip gray">{g}</span>)}</div>
            </div>
            <div>
              <div className="mix-label" style={{ marginBottom: 6 }}>Descriptions</div>
              {(coach.ads?.descriptions || []).map((d: string, i: number) => (
                <div key={i} style={{ fontSize: 12, padding: "4px 0", color: "var(--text2)" }}>• {d}</div>
              ))}
              <div className="mix-label" style={{ margin: "10px 0 6px" }}>Sitelinks / callouts</div>
              <div className="mix-row">{[...(coach.ads?.sitelinks || []), ...(coach.ads?.callouts || [])].map((s: string, i: number) => <span key={i} className="mix-chip blue">{s}</span>)}</div>
            </div>
          </div>
          <div className="policy-check" style={{ marginTop: 14, background: "var(--blue-lt)", borderColor: "var(--blue-mid)", color: "var(--blue)" }}>
            <Icon d={ICONS.help} size={13} />{coach.ads?.quality_score_note}
          </div>
        </div>

        {/* Reviews + Landing */}
        <div className="two-col-wide">
          <div className="card">
            <div className="card-title"><Icon d={ICONS.star} size={15} color="var(--amber)" />Review assistant</div>
            <div className="card-subtitle">Respond to real reviews &amp; request honest ones. Never fake.</div>
            {coach.reviews?.summary?.available ? (
              <div style={{ marginBottom: 10, fontSize: 12.5 }}>
                <b>Themes:</b> {(coach.reviews.summary.themes || []).join(", ") || "—"}
                {coach.reviews.summary.complaints?.length > 0 && (
                  <div style={{ color: "var(--amber)", marginTop: 4 }}><b>Watch:</b> {coach.reviews.summary.complaints.join(", ")}</div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>Not enough review signal yet — focus on requesting honest reviews after matchday.</div>
            )}
            <div className="card-divider" />
            <div className="mix-label" style={{ marginBottom: 6 }}>Draft a reply to a real review</div>
            <textarea value={reviewText} onChange={e => setReviewText(e.target.value)} placeholder="Paste a customer review…"
              style={{ width: "100%", minHeight: 56, background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, padding: 10, fontSize: 12.5, color: "var(--text)", resize: "vertical" }} />
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
              <select value={reviewRating} onChange={e => setReviewRating(Number(e.target.value))} style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, padding: "6px 10px", fontSize: 12.5 }}>
                {[5, 4, 3, 2, 1].map(n => <option key={n} value={n}>{n}★</option>)}
              </select>
              <button className="btn-primary" style={{ padding: "8px 14px" }} onClick={onReply}>Draft reply</button>
            </div>
            {reviewReply && (
              <div style={{ marginTop: 10, background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, padding: 10 }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>Suggested reply ({reviewReply.sentiment}):</div>
                <div style={{ fontSize: 12.5, color: "var(--text2)" }}>{reviewReply.response}</div>
                <CopyBtn text={reviewReply.response} />
              </div>
            )}
            <div className="card-divider" />
            <div className="mix-label" style={{ marginBottom: 6 }}>Ethical review request</div>
            <div style={{ fontSize: 12.5, color: "var(--text2)", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 8, padding: 10 }}>
              {coach.reviews?.request_copy?.request_copy?.en}
              <CopyBtn text={coach.reviews?.request_copy?.request_copy?.en || ""} />
            </div>
          </div>

          <div className="card">
            <div className="card-title"><Icon d={ICONS.link} size={15} color="var(--blue)" />Landing-page readiness</div>
            {coach.landing?.has_website ? (<>
              <div className="card-subtitle">For ad clicks to convert, the page must match the ad. Score: {coach.landing.score}/100 confirmable.</div>
              {(coach.landing.confirmed || []).map((c: any, i: number) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12.5, padding: "3px 0" }}>
                  <span style={{ color: c.status === "yes" ? "var(--green)" : "var(--faint)", fontWeight: 700 }}>{c.status === "yes" ? "✓" : "○"}</span>
                  <span style={{ color: "var(--text2)" }}>{c.item}</span>
                </div>
              ))}
              <div className="mix-label" style={{ margin: "10px 0 6px" }}>Verify on your page</div>
              {(coach.landing.self_check || []).map((c: any, i: number) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, padding: "2px 0", color: "var(--muted)" }}>
                  <span>◇</span><span>{c.item}</span>
                </div>
              ))}
            </>) : (
              <div className="card-subtitle">{coach.landing?.message}</div>
            )}
          </div>
        </div>

        <div style={{ fontSize: 11, color: "var(--muted)", textAlign: "center", padding: "4px 0" }}>
          {coach.privacy_note}
        </div>
      </>)}
    </div>
  );
}

// ── Per-business Intelligence profile ─────────────────────────────────────────
function BusinessIntelView({ bizId, eventId, onBack }: { bizId: string; eventId: string; onBack: () => void }) {
  const [p, setP] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!bizId || !eventId) return;
    setLoading(true); setP(null);
    getBusinessIntel(bizId, eventId).then(setP).catch(() => {}).finally(() => setLoading(false));
  }, [bizId, eventId]);

  if (loading) return <div className="card"><div className="empty-state"><div className="spinner" style={{ width: 28, height: 28, margin: "0 auto 12px" }} />Building intelligence profile…</div></div>;
  if (!p || p.error) return <div className="card"><button className="section-link" onClick={onBack}>← Back</button><div className="empty-state">Could not load profile.</div></div>;

  const VERDICT: any = {
    capitalize_world_cup: { label: "Capitalize on the World Cup", cls: "green" },
    balanced: { label: "Balanced: ads + organic", cls: "blue" },
    food_focus_plus_organic: { label: "Focus on food + organic", cls: "amber" },
    fix_fundamentals_first: { label: "Fix fundamentals first", cls: "amber" },
  };
  const v = VERDICT[p.strategy?.verdict] || { label: p.strategy?.verdict, cls: "blue" };
  const rk = p.ranking, w = p.website, a = p.atmosphere, rv = p.reviews, loc = p.location_and_demographics;
  const wg = a?.watch_the_game_inside;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <button className="section-link" onClick={onBack} style={{ marginTop: 0 }}>← Back to businesses</button>

      {/* header */}
      <div className="card">
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 19, fontWeight: 800, color: "var(--text)" }}>{p.name}</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)", textTransform: "capitalize" }}>
              {p.kind} · {p.category?.replace(/_/g, " ")} · {(loc?.neighborhood || "").replace(/_/g, " ")}
              {" · "}{rk?.distance_to_venue_km}km from venue
            </div>
            {p.local_archetype?.characterization && (
              <div style={{ marginTop: 8, display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 11px", background: "var(--teal-lt)", border: "1px solid var(--teal-mid)", borderRadius: 999 }}>
                <span style={{ fontSize: 13 }}>{p.local_archetype.established_year ? "🏛️" : "🏠"}</span>
                <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--teal)" }}>{p.local_archetype.characterization}</span>
              </div>
            )}
            <div style={{ marginTop: 8, fontSize: 13, color: "var(--text2)" }}>
              {p.what_they_sell?.editorial_summary || `Sells: ${(p.what_they_sell?.primary_offering || []).join(", ")}`}
            </div>
            <div className="mix-row" style={{ marginTop: 8 }}>
              {(p.what_they_sell?.primary_offering || []).map((t: string) => <span key={t} className="mix-chip blue">{t.replace(/_/g, " ")}</span>)}
            </div>
          </div>
          <div style={{ textAlign: "center", flexShrink: 0 }}>
            <ScoreGauge score={rk?.matchday_search_readiness ?? 0} />
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>Search Readiness</div>
          </div>
        </div>
        <div className={`policy-check`} style={{ marginTop: 12, background: `var(--${v.cls}-lt)`, borderColor: `var(--${v.cls})`, color: `var(--${v.cls})` }}>
          <Icon d={ICONS.spark} size={13} /> Strategy: <b>{v.label}</b>
        </div>
        <div style={{ fontSize: 12.5, color: "var(--text2)", marginTop: 8 }}>{p.strategy?.ad_vs_food}</div>
      </div>

      {/* KPI row */}
      <div className="kpi-row">
        {[
          { icon: "star", cls: "amber", label: "Rating", value: rv?.rating ? `${rv.rating}★` : "—", sub: `${rv?.review_count ?? 0} reviews` },
          { icon: "eye", cls: "blue", label: "Readiness", value: `${rk?.matchday_search_readiness}/100`, sub: rk?.band },
          { icon: "trending", cls: "teal", label: "Prominence", value: `${Math.round((rk?.prominence_score ?? 0) * 100)}%`, sub: "rating × volume" },
          { icon: "map", cls: "blue", label: "Distance", value: `${rk?.distance_to_venue_km}km`, sub: loc?.fan_flow },
        ].map((c, i) => (
          <div key={i} className="kpi-card">
            <div className="kpi-header"><div className={`kpi-icon ${c.cls}`}><Icon d={ICONS[c.icon as keyof typeof ICONS]} size={14} color={`var(--${c.cls})`} /></div><span className="kpi-label">{c.label}</span></div>
            <div className="kpi-value">{c.value}</div><div className="kpi-sub">{c.sub}</div>
          </div>
        ))}
      </div>

      {/* What they offer that chains don't + how Google ranks this */}
      <div className="two-col-wide">
        <div className="card" style={{ background: "var(--teal-lt)", borderColor: "var(--teal-mid)" }}>
          <div className="card-title"><Icon d={ICONS.star} size={15} color="var(--teal)" />What a chain can't replicate here</div>
          <div style={{ fontSize: 13, color: "var(--text2)" }}>{p.local_character?.what_chains_dont_offer}</div>
          <div className="mix-row" style={{ marginTop: 10 }}>
            {p.local_character?.cuisine && <span className="mix-chip teal">{p.local_character.cuisine}</span>}
            {(p.local_character?.cooking_style || []).slice(0, 2).map((s: string, i: number) => <span key={"st" + i} className="mix-chip gray">{s.split(" — ")[0].split(" (")[0]}</span>)}
            {(p.local_character?.freshness || []).slice(0, 1).map((s: string, i: number) => <span key={"fr" + i} className="mix-chip gray">{s.split(" — ")[0]}</span>)}
            {(p.local_character?.story || []).slice(0, 2).map((s: string, i: number) => <span key={"sy" + i} className="mix-chip blue">{s}</span>)}
          </div>
          {p.local_archetype && (
            <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--teal-mid)", display: "grid", gap: 4 }}>
              <div style={{ fontSize: 12.5 }}><b>How long:</b> {p.local_archetype.longevity?.value}
                <span style={{ color: "var(--muted)", fontSize: 11 }}> ({p.local_archetype.longevity?.confidence} confidence — {p.local_archetype.longevity?.basis})</span></div>
              <div style={{ fontSize: 12.5 }}><b>Originated here?</b> {String(p.local_archetype.local_origin?.locally_originated)} — {p.local_archetype.local_origin?.note}</div>
              <div style={{ fontSize: 12.5 }}><b>Culture:</b> {p.local_archetype.cultural_heritage?.note}</div>
              <div style={{ fontSize: 10.5, color: "var(--muted)", fontStyle: "italic" }}>{p.local_archetype.cultural_heritage?.privacy || "Food heritage only — never a person's origin."}</div>
            </div>
          )}
        </div>
        <div className="card">
          <div className="card-title"><Icon d={ICONS.help} size={15} color="var(--blue)" />How Google ranks this</div>
          <div style={{ fontSize: 12, color: "var(--text2)" }}>{p.ranking_model?.why_gems_sit_low}</div>
          <div style={{ marginTop: 8, fontSize: 11.5, color: "var(--muted)" }}>
            <div><b style={{ color: "var(--blue)" }}>Relevance</b> {p.ranking_model?.pillars?.relevance}</div>
            <div style={{ marginTop: 3 }}><b style={{ color: "var(--blue)" }}>Distance</b> {p.ranking_model?.pillars?.distance}</div>
            <div style={{ marginTop: 3 }}><b style={{ color: "var(--blue)" }}>Prominence</b> {p.ranking_model?.pillars?.prominence}</div>
          </div>
          <div className="policy-check" style={{ marginTop: 10, background: "var(--teal-lt)", borderColor: "var(--teal-mid)", color: "var(--teal)" }}>
            <Icon d={ICONS.plan} size={13} />{p.ranking_model?.controllable_lever}
          </div>
        </div>
      </div>

      <div className="two-col-wide">
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {/* Reviews — honest verdict, why loved (or not), why not higher */}
          <div className="card">
            <div className="card-title"><Icon d={ICONS.star} size={15} color="var(--amber)" />Reviews — the honest read</div>
            {rv?.quality_verdict && (() => {
              const v = rv.quality_verdict;
              const good = v === "genuinely loved" || v === "well-regarded";
              const bad = v === "below average" || v === "poorly rated";
              const col = good ? "teal" : bad ? "red" : "amber";
              return (
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: ".04em", color: `var(--${col})`, background: `var(--${col}-lt)`, border: `1px solid var(--${col})`, padding: "3px 9px", borderRadius: 999 }}>{v}</span>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>{rv.verdict_note}</span>
                </div>
              );
            })()}
            <div style={{ fontSize: 13, color: "var(--text2)" }}>{rv?.how_they_carry}</div>
            {rv?.concerns?.length > 0 && (
              <div style={{ marginTop: 8, padding: "8px 11px", background: "var(--red-lt)", border: "1px solid var(--red)", borderRadius: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--red)", textTransform: "uppercase", letterSpacing: ".04em" }}>Real concerns from reviews</div>
                <div style={{ fontSize: 12.5, color: "var(--text2)", marginTop: 3 }}>{rv.concerns.join(" · ")}</div>
              </div>
            )}
            {rv?.why_locals_love_it && (
              <div style={{ marginTop: 10, padding: "8px 11px", background: "var(--teal-lt)", border: "1px solid var(--teal-mid)", borderRadius: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--teal)", textTransform: "uppercase", letterSpacing: ".04em" }}>Why locals love it</div>
                <div style={{ fontSize: 12.5, color: "var(--text2)", marginTop: 3 }}>{rv.why_locals_love_it}</div>
              </div>
            )}
            {rv?.why_not_ranked_higher && (
              <div style={{ marginTop: 8, padding: "8px 11px", background: "var(--amber-lt)", border: "1px solid #fde68a", borderRadius: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--amber)", textTransform: "uppercase", letterSpacing: ".04em" }}>Why it's not ranked higher</div>
                <div style={{ fontSize: 12.5, color: "var(--text2)", marginTop: 3 }}>{rv.why_not_ranked_higher}</div>
              </div>
            )}
            {rv?.sample_snippets?.length > 0 && (
              <div style={{ marginTop: 10 }}>
                {rv.sample_snippets.map((s: string, i: number) => (
                  <div key={i} style={{ fontSize: 12, color: "var(--muted)", fontStyle: "italic", borderLeft: "2px solid var(--border2)", paddingLeft: 8, marginTop: 5 }}>“{s.length > 160 ? s.slice(0, 160) + "…" : s}”</div>
                ))}
              </div>
            )}
            {rv?.complaints?.length > 0 && <div style={{ marginTop: 8, fontSize: 12.5, color: "var(--amber)" }}><b>Watch:</b> {rv.complaints.join(", ")}</div>}
            <div style={{ marginTop: 8, fontSize: 11, color: "var(--muted)" }}>Recency: {rv?.recency}</div>
            <div style={{ marginTop: 4, fontSize: 10.5, color: "var(--faint)", fontStyle: "italic", borderTop: "1px solid var(--border)", paddingTop: 6 }}>
              <Icon d={ICONS.shield} size={10} /> {rv?.provenance}
            </div>
          </div>
          {/* Website */}
          <div className="card">
            <div className="card-title"><Icon d={ICONS.link} size={15} color="var(--blue)" />Website</div>
            {w?.has_website ? (
              <div style={{ fontSize: 13 }}>
                <a href={w.url} target="_blank" rel="noreferrer" style={{ color: "var(--blue)" }}>{w.url}</a>
                <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>{w.why_it_matters}</div>
              </div>
            ) : (
              <div style={{ fontSize: 12.5, color: "var(--text2)" }}>
                <div style={{ fontWeight: 700, color: "var(--amber)" }}>No website on file</div>
                <div style={{ marginTop: 4 }}>{w?.likely_reason}</div>
                <div style={{ marginTop: 6 }}><b>Impact:</b> {w?.ranking_impact}</div>
                <div style={{ marginTop: 6, color: "var(--teal)" }}><b>Fix:</b> {w?.fix}</div>
              </div>
            )}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {/* Atmosphere + watch the game */}
          <div className="card">
            <div className="card-title"><Icon d={ICONS.users} size={15} color="var(--blue)" />Atmosphere</div>
            <div className="mix-row">{(a?.signals || []).map((s: string) => <span key={s} className="mix-chip gray">{s}</span>)}</div>
            {!a?.signals?.length && <div style={{ fontSize: 12, color: "var(--muted)" }}>{a?.note}</div>}
            <div className="card-divider" />
            <div style={{ fontSize: 12.5 }}>
              <b>Watch the game inside?</b>{" "}
              <span style={{ color: wg?.answer === "likely yes" ? "var(--green)" : wg?.answer === "no signal" ? "var(--muted)" : "var(--amber)", fontWeight: 700, textTransform: "capitalize" }}>{wg?.answer}</span>
              <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 3 }}>{wg?.basis}</div>
            </div>
          </div>
          {/* Why ranked + demographics */}
          <div className="card">
            <div className="card-title"><Icon d={ICONS.chart} size={15} color="var(--blue)" />Why it ranks where it does</div>
            <div style={{ fontSize: 12.5, color: "var(--text2)" }}>{rk?.why_ranked_here}</div>
            <div className="card-divider" />
            <div style={{ fontSize: 12.5, color: "var(--text2)" }}>{loc?.how_inflow_helps}</div>
            {loc?.aggregate_language_demand?.length > 0 && (
              <div className="mix-row" style={{ marginTop: 8 }}>
                {loc.aggregate_language_demand.map((l: string) => <span key={l} className="mix-chip teal">{l.toUpperCase()}</span>)}
              </div>
            )}
            <div style={{ marginTop: 8, fontSize: 11, color: "var(--muted)" }}>{loc?.privacy_note}</div>
          </div>
        </div>
      </div>

      {/* top fixes */}
      {p.top_controllable_fixes?.length > 0 && (
        <div className="card">
          <div className="card-title"><Icon d={ICONS.plan} size={15} color="var(--teal)" />Top controllable fixes</div>
          <ul className="fix-list">
            {p.top_controllable_fixes.map((f: string, i: number) => (
              <li key={i} className="fix-item"><span className="fix-dot" style={{ background: "var(--teal)" }} />{f}</li>
            ))}
          </ul>
        </div>
      )}
      <div style={{ fontSize: 11, color: "var(--muted)", textAlign: "center" }}>{p.disclaimer}</div>
    </div>
  );
}

// ── Businesses table (Opportunity + Hidden Gems) ──────────────────────────────
function BusinessesView({ eventId, eventLabel }: { eventId: string; eventLabel: string }) {
  const [tab, setTab] = useState<"opportunity" | "gems">("opportunity");
  const [rows, setRows] = useState<any[]>([]);
  const [meta, setMeta] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    if (!eventId || openId) return;
    setLoading(true);
    const fn = tab === "opportunity" ? getRankedBusinesses(eventId, "", 30) : getHiddenGems(eventId, "", 25);
    fn.then((r: any) => {
      setMeta(r);
      setRows(tab === "opportunity" ? (r.businesses || []) : (r.hidden_gems || []));
    }).catch(() => {}).finally(() => setLoading(false));
  }, [eventId, tab, openId]);

  if (openId) return <BusinessIntelView bizId={openId} eventId={eventId} onBack={() => setOpenId(null)} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="card" style={{ background: "var(--blue-lt)", borderColor: "var(--blue-mid)" }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Businesses near {eventLabel}</div>
        <div style={{ fontSize: 12.5, color: "var(--text2)" }}>
          {tab === "opportunity"
            ? "Ranked by matchday opportunity — distance to fan flow, relevance, prominence, and conversion readiness. Real Google businesses only."
            : "Locally-loved independents buried under chains' review volume — surfaced with their real ratings as assurance. Authentic over big-fanbase."}
        </div>
      </div>

      <div className="mode-tabs" style={{ maxWidth: 420 }}>
        <button className={`mode-tab${tab === "opportunity" ? " active" : ""}`} onClick={() => setTab("opportunity")}>📊 Opportunity</button>
        <button className={`mode-tab${tab === "gems" ? " active" : ""}`} onClick={() => setTab("gems")}>💎 Hidden gems</button>
      </div>

      {/* ranking explainer + tier summary (gems tab) */}
      {tab === "gems" && meta?.ranking_model && (
        <div className="card" style={{ background: "var(--surface2)" }}>
          <div className="card-title" style={{ margin: 0 }}><Icon d={ICONS.help} size={14} color="var(--blue)" />How Google ranks local businesses — and why these gems sit low</div>
          <div style={{ fontSize: 12, color: "var(--text2)", marginTop: 6 }}>{meta.ranking_model.why_gems_sit_low}</div>
          <div style={{ display: "flex", gap: 14, marginTop: 8, flexWrap: "wrap", fontSize: 11.5, color: "var(--muted)" }}>
            <span><b style={{ color: "var(--blue)" }}>Relevance</b> · category/menu/language</span>
            <span><b style={{ color: "var(--blue)" }}>Distance</b> · structural</span>
            <span><b style={{ color: "var(--blue)" }}>Prominence</b> · review COUNT + links (favors chains)</span>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            {["secret", "underrated", "local_favorite"].map(t => meta.tier_counts?.[t] != null && (
              <span key={t} className="mix-chip" style={{ background: t === "secret" ? "var(--teal-lt)" : t === "underrated" ? "var(--blue-lt)" : "var(--surface2)", borderColor: t === "secret" ? "var(--teal-mid)" : "var(--blue-mid)", color: t === "secret" ? "var(--teal)" : t === "underrated" ? "var(--blue)" : "var(--muted)" }}>
                {t.replace(/_/g, " ")}: {meta.tier_counts[t]}
              </span>
            ))}
            <span className="mix-chip gray">controllable lever: earn honest reviews from every customer</span>
          </div>
        </div>
      )}

      {loading && <div className="card"><div className="empty-state"><div className="spinner" style={{ width: 26, height: 26, margin: "0 auto 10px" }} />Loading…</div></div>}

      {!loading && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="biz-table">
            <thead>
              <tr>
                <th>#</th><th>Business</th><th>Type</th><th>Rating</th>
                <th>{tab === "opportunity" ? "Opportunity" : "Gem score"}</th>
                <th>Dist</th><th>{tab === "opportunity" ? "Move" : "Buried under"}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b, i) => (
                <tr key={b.business_id} onClick={() => setOpenId(b.business_id)} className="biz-row">
                  <td className="biz-rank">{i + 1}</td>
                  <td>
                    <div className="biz-name">{b.name}
                      {tab === "gems" && b.discovery_tier && (
                        <span className="gem-badge" style={{ background: b.discovery_tier === "secret" ? "var(--teal)" : b.discovery_tier === "underrated" ? "var(--blue)" : "var(--faint)" }}>
                          {b.discovery_tier === "secret" ? "secret" : b.discovery_tier === "underrated" ? "underrated" : "local fav"}
                        </span>
                      )}
                    </div>
                    <div className="biz-sub">{(b.neighborhood || "").replace(/_/g, " ")}{!b.has_website && " · no website"}</div>
                    {tab === "gems" && b.why_loved && <div className="biz-sub" style={{ color: "var(--teal)" }}>♥ {b.why_loved}</div>}
                    {tab === "gems" && b.local_character?.what_chains_dont_offer && (
                      <div className="biz-sub" style={{ color: "var(--text2)", marginTop: 2 }}>{b.local_character.what_chains_dont_offer}</div>
                    )}
                  </td>
                  <td style={{ textTransform: "capitalize", color: "var(--muted)", fontSize: 12 }}>{b.kind}</td>
                  <td><span className="biz-rating">{b.rating ?? "—"}★</span> <span className="biz-sub">{b.reviews ?? 0}</span></td>
                  <td><span className="biz-score">{tab === "opportunity" ? b.opportunity : b.gem_score}</span></td>
                  <td className="biz-sub">{b.distance_km}km</td>
                  <td className="biz-move">
                    {tab === "opportunity" ? b.top_move
                      : (b.prominence_gap ? `${b.prominence_gap.ratio}× fewer reviews than ${b.overshadowed_by?.name}`
                        : b.overshadowed_by ? `${b.overshadowed_by.name} (${b.overshadowed_by.reviews} rev)` : "—")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ fontSize: 11, color: "var(--muted)", textAlign: "center" }}>{meta?.note}</div>
    </div>
  );
}

// ── Main Dashboard ───────────────────────────────────────────────────────────
export default function Dashboard() {
  const [events, setEvents] = useState<any[]>([]);
  const [businesses, setBusinesses] = useState<any[]>([]);
  const [eventId, setEventId] = useState("");
  const [bizId, setBizId] = useState("");
  const [mix, setMix] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [generating, setGenerating] = useState(false);
  const [activeNav, setActiveNav] = useState("overview");
  const [mode, setMode] = useState<"owner" | "visitor">("owner");
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  useEffect(() => {
    getEvents().then(e => { setEvents(e); if (e[0]) setEventId(e[0]._id); }).catch(() => {});
    getBusinesses().then(b => { setBusinesses(b); if (b[0]) setBizId(b[0]._id); }).catch(() => {});
  }, []);

  useEffect(() => {
    if (eventId) getMarketMix(eventId).then(setMix).catch(() => {});
  }, [eventId]);

  async function onGenerate() {
    if (!bizId || !eventId) return;
    setGenerating(true); setPlan(null);
    try {
      const p = await generatePlan(bizId, eventId);
      setPlan(p);
      setLastUpdated("just now");
    } finally { setGenerating(false); }
  }

  async function onApprove() {
    if (!plan?._id) return;
    const updated = await approvePlan(plan._id);
    setPlan(updated);
  }

  const selectedEvent = events.find(e => e._id === eventId);
  const selectedBiz   = businesses.find(b => b._id === bizId);

  const eventLabel = selectedEvent
    ? `${selectedEvent.team_home_name} vs ${selectedEvent.team_away_name}`
    : "Select a match";
  const eventSub = selectedEvent
    ? `${new Date(selectedEvent.kickoff_local).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })} · ${selectedEvent.venue_name}`
    : "";

  return (
    <div className="app-shell">
      <Sidebar active={activeNav} onNav={setActiveNav} />

      <div className="main-area">
        {/* Top bar */}
        <header className="topbar">
          <div className="topbar-left">
            <span className="topbar-page-title">
              {NAV_ITEMS.find(n => n.id === activeNav)?.label || "Overview"}
            </span>
          </div>
          <div className="topbar-right">
            <div className="privacy-badge">
              <Icon d={ICONS.shield} size={12} />
              Privacy-safe · Aggregated signals only. No individual data.
            </div>
            <button className="icon-btn" title="Help"><Icon d={ICONS.help} size={15} /></button>
            <button className="icon-btn" title="Notifications"><Icon d={ICONS.bell} size={15} /></button>
            <div className="avatar">AM</div>
          </div>
        </header>

        {/* Page content */}
        <main className="page-content">

          {/* ── GOOGLE GROWTH COACH ── */}
          {activeNav === "growth" && (
            <GrowthCoachView businesses={businesses} events={events}
              bizId={bizId} setBizId={setBizId} eventId={eventId} setEventId={setEventId} />
          )}

          {/* ── BUSINESSES (ranked + hidden gems + intel) ── */}
          {activeNav === "businesses" && (
            <BusinessesView eventId={eventId} eventLabel={eventLabel} />
          )}

          {activeNav !== "growth" && activeNav !== "businesses" && (<>

          {/* Mode toggle */}
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div className="mode-tabs" style={{ maxWidth: 320 }}>
              <button className={`mode-tab${mode === "owner" ? " active" : ""}`} onClick={() => setMode("owner")}>
                🏪 Business owner
              </button>
              <button className={`mode-tab${mode === "visitor" ? " active" : ""}`} onClick={() => setMode("visitor")}>
                ⚽ Visiting fan
              </button>
            </div>
            <div style={{ flex: 1 }} />
            {lastUpdated && <span className="last-updated">Last updated: {lastUpdated} <Icon d={ICONS.refresh} size={11} /></span>}
          </div>

          {/* ── OWNER MODE ── */}
          {mode === "owner" && (<>

            {/* Control row */}
            <div className="control-row">
              <div className="selector-outer">
                <div className="selector-label">Business</div>
                <div className="selector" style={{ position: "relative" }}>
                  <div className="selector-icon">🏪</div>
                  <div className="selector-text">
                    <div className="selector-main">{selectedBiz?.name || "Select a business"}</div>
                    <div className="selector-sub">{selectedBiz ? `${selectedBiz.category} · ${selectedBiz.neighborhood_id?.replace(/_/g, " ")}` : "No business selected"}</div>
                  </div>
                  <span className="selector-chevron">▾</span>
                  <select
                    value={bizId} onChange={e => setBizId(e.target.value)}
                    style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer", width: "100%", height: "100%" }}
                  >
                    {businesses.map(b => <option key={b._id} value={b._id}>{b.name}</option>)}
                  </select>
                </div>
              </div>

              <div className="control-divider" />

              <div className="selector-outer">
                <div className="selector-label">Match</div>
                <div className="selector" style={{ position: "relative" }}>
                  <div className="selector-icon">⚽</div>
                  <div className="selector-text">
                    <div className="selector-main">{eventLabel}</div>
                    <div className="selector-sub">{eventSub || "No match selected"}</div>
                  </div>
                  <span className="selector-chevron">▾</span>
                  <select
                    value={eventId} onChange={e => setEventId(e.target.value)}
                    style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer", width: "100%", height: "100%" }}
                  >
                    {events.map(ev => (
                      <option key={ev._id} value={ev._id}>
                        {ev.team_home_name} vs {ev.team_away_name} · {ev.kickoff_local?.slice(0, 10)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div style={{ marginLeft: "auto" }}>
                <button className="btn-primary" onClick={onGenerate} disabled={generating || !bizId || !eventId}>
                  {generating ? <><div className="spinner" style={{ borderTopColor: "#fff", width: 14, height: 14 }} /> Generating…</> : <><Icon d={ICONS.spark} size={15} /> Generate action plan</>}
                </button>
              </div>
            </div>

            {/* KPI cards */}
            {plan && <OwnerKPICards plan={plan} />}

            {!plan && !generating && (
              <div className="card">
                <div className="empty-state">
                  <div className="empty-state-icon">📊</div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text2)", marginBottom: 6 }}>
                    Select a business and match, then generate your action plan
                  </div>
                  <div style={{ color: "var(--muted)", maxWidth: 400, margin: "0 auto" }}>
                    FanFlow AI analyzes matchday demand, visitor flow, language opportunity, and visibility gaps to give you a prioritised action plan.
                  </div>
                </div>
              </div>
            )}

            {generating && (
              <div className="card">
                <div className="empty-state">
                  <div className="spinner" style={{ width: 32, height: 32, borderWidth: 3, margin: "0 auto 16px" }} />
                  <div style={{ fontWeight: 600, color: "var(--text2)" }}>Generating your demand intelligence report…</div>
                </div>
              </div>
            )}

            {/* Main grid: demand chart + visitor mix */}
            <div className="two-col">
              <div className="card">
                <div className="card-title" style={{ marginBottom: 2 }}>
                  <Icon d={ICONS.chart} size={15} color="var(--blue)" />
                  Matchday demand forecast
                </div>
                <div className="card-subtitle">Expected visitor demand vs a normal Saturday</div>
                <DemandChart matchName={eventLabel} />
              </div>
              {mix && <VisitorMixCard mix={mix} />}
            </div>

            {/* Plan section */}
            {plan && (
              <>
                {/* Source market from plan */}
                {plan.business_name && (
                  <div className="card" style={{ background: "var(--blue-lt)", borderColor: "var(--blue-mid)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--blue)", marginBottom: 2 }}>
                          {plan.business_name} — {plan.match}
                        </div>
                        <div style={{ fontSize: 13, color: "var(--text2)" }}>{plan.why}</div>
                      </div>
                      {plan.status !== "approved" && (
                        <button className="btn-primary" onClick={onApprove} style={{ background: "var(--teal)" }}>
                          Approve &amp; stage
                        </button>
                      )}
                      {plan.status === "approved" && (
                        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--green)", background: "var(--green-lt)", padding: "6px 14px", borderRadius: 999, border: "1px solid #bbf7d0" }}>
                          ✓ Approved — staged for publish
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* Staffing + Inventory */}
                {(plan.staffing?.length > 0 || plan.inventory?.length > 0) && (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
                    {plan.staffing?.length > 0 && (
                      <div className="card">
                        <div className="card-title"><Icon d={ICONS.users} size={15} color="var(--blue)" />Staffing &amp; hours</div>
                        <div className="card-subtitle">Recommended shifts for matchday.</div>
                        <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                          {plan.staffing.map((s: any, i: number) => (
                            <li key={i} style={{ display: "flex", justifyContent: "space-between", padding: "6px 10px", background: "var(--surface2)", borderRadius: 7, fontSize: 12.5, border: "1px solid var(--border)" }}>
                              <span style={{ color: "var(--muted)" }}>{s.hour}</span>
                              <span style={{ fontWeight: 700 }}>{s.staff} staff</span>
                              <span style={{ color: "var(--muted)" }}>~{s.expected_walkins} walk-ins</span>
                            </li>
                          ))}
                        </ul>
                        <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--text2)" }}><b>Hours:</b> {plan.hours_change}</div>
                      </div>
                    )}
                    {plan.inventory?.length > 0 && (
                      <div className="card">
                        <div className="card-title"><Icon d={ICONS.trending} size={15} color="var(--blue)" />Inventory</div>
                        <div className="card-subtitle">Suggested stock increases for the surge window.</div>
                        <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                          {plan.inventory.map((item: any, i: number) => (
                            <li key={i} style={{ display: "flex", justifyContent: "space-between", padding: "6px 10px", background: "var(--surface2)", borderRadius: 7, fontSize: 12.5, border: "1px solid var(--border)" }}>
                              <span style={{ fontWeight: 600 }}>{item.item}</span>
                              <span style={{ color: "var(--green)", fontWeight: 700 }}>+{item.increase_pct}%</span>
                              <span style={{ color: "var(--muted)" }}>{item.why}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}

                {/* Visibility + Actions */}
                <div className="two-col-wide">
                  <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                    <ActionPlanCard plan={plan} />
                    <MultilingualCard plan={plan} />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                    <VisibilityCard plan={plan} />
                    <RisksCard plan={plan} />
                  </div>
                </div>

                {/* Agent chat */}
                <div className="card">
                  <div className="card-title"><Icon d={ICONS.spark} size={15} color="var(--blue)" />Ask the agent</div>
                  <div className="card-subtitle">Ask about staffing, inventory, visibility, or how to prepare. Falls back to plan data if Gemini is not configured.</div>
                  <AgentChat bizId={bizId} eventId={eventId} />
                </div>
              </>
            )}

            {/* Always show visibility + actions even without a plan */}
            {!plan && !generating && (
              <div className="two-col-wide">
                <ActionPlanCard plan={null} />
                <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                  <VisibilityCard plan={null} />
                  <RisksCard plan={null} />
                </div>
              </div>
            )}

          </>)}

          {/* ── VISITOR MODE ── */}
          {mode === "visitor" && (
            <VisitorMode eventId={eventId} />
          )}

          </>)}

        </main>

        <footer className="page-footer">
          FanFlow AI uses aggregated, privacy-safe signals to help local businesses win on matchdays. · Google Cloud Rapid Agent Hackathon 2026
        </footer>
      </div>
    </div>
  );
}
