"use client";
import { useEffect, useRef, useState } from "react";
import { getEvents, visitorChat } from "../../lib/api";

// ── FanFlow mobile fan app — phone-framed, World-Cup themed, Claude-mobile aesthetic ──────────
type Msg = { who: "bot" | "you"; text?: string; recs?: any[]; venues?: any[]; kind?: string };

const QUICK = [
  "Best tacos near Levi's",
  "Where can I watch the game?",
  "Hidden local gems, not chains",
  "Family spot before kickoff",
];

const SLOT_LABEL: Record<string, string> = {
  primary_fit: "Best fit",
  local_alternative: "Local favorite",
  backup: "Backup if it's busy",
  worth_trying: "Worth trying",
  soccer_pick: "Watch the match",
};

function SoccerBall({ size = 18, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className}>
      <circle cx="16" cy="16" r="15" fill="#fff" stroke="#0d1b12" strokeWidth="1.5" />
      <path d="M16 7l5 3.6-1.9 5.9h-6.2L11 10.6 16 7z" fill="#0d1b12" />
      <path d="M16 7V3.5M21 10.6l3.3-1.2M19.1 16.5l2.6 2.2M12.9 16.5l-2.6 2.2M11 10.6L7.7 9.4"
        stroke="#0d1b12" strokeWidth="1.3" strokeLinecap="round" fill="none" />
    </svg>
  );
}

export default function FanApp() {
  const [events, setEvents] = useState<any[]>([]);
  const [eventId, setEventId] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([{
    who: "bot",
    text: "⚽ Welcome to FanFlow! I'm your local matchday guide. Ask me anything in any language — I'll point you to real local spots near the stadium. I never guess where you're from; I just go on what you're after.",
  }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [settings, setSettings] = useState(false);
  const history = useRef<string[]>([]);
  const rejected = useRef<string[]>([]);
  const scroll = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getEvents().then(e => { setEvents(e); if (e[0]) setEventId(e[0]._id); }).catch(() => {});
  }, []);
  useEffect(() => { scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: "smooth" }); }, [msgs, loading]);

  const ev = events.find(e => e._id === eventId);

  async function send(q?: string) {
    const text = (q ?? input).trim();
    if (!text || loading) return;
    setInput("");
    setMsgs(m => [...m, { who: "you", text }]);
    setLoading(true);
    try {
      const r = await visitorChat(text, eventId, {}, history.current, rejected.current);
      history.current = [...history.current, text];
      if (r.mode === "refusal" || r.mode === "followup" || r.mode === "out_of_area") {
        setMsgs(m => [...m, { who: "bot", text: r.message }]);
      } else if (r.soccer_venues?.length) {
        setMsgs(m => [...m, { who: "bot", text: r.message, venues: r.soccer_venues, kind: "venues" }]);
      } else {
        const recs = Object.entries(r.recommendations || {})
          .map(([slot, c]: any) => c && ({ ...c, slot })).filter(Boolean);
        recs.forEach((c: any) => c.place_id && rejected.current.push(c.place_id));
        setMsgs(m => [...m, { who: "bot", text: r.message, recs }]);
      }
    } catch {
      setMsgs(m => [...m, { who: "bot", text: "Hmm, I couldn't reach the guide. Try again in a moment." }]);
    } finally { setLoading(false); }
  }

  return (
    <div className="ff-wrap">
      <style dangerouslySetInnerHTML={{ __html: FF_CSS }} />
      <div className="ff-phone">
        {/* status bar */}
        <div className="ff-status">
          <span>9:41</span>
          <span className="ff-status-icons"><SoccerBall size={11} /> ◍ ▰▰▰</span>
        </div>

        {/* header */}
        <header className="ff-header">
          <div className="ff-brand">
            <div className="ff-logo"><SoccerBall size={20} /></div>
            <div>
              <div className="ff-title">FanFlow</div>
              <div className="ff-sub">{ev?.venue_name ? `Local food near ${ev.venue_name}` : "Local food guide"}</div>
            </div>
          </div>
          <button className="ff-menu" onClick={() => setSettings(true)} aria-label="menu">
            <SoccerBall size={9} /><SoccerBall size={9} /><SoccerBall size={9} />
          </button>
        </header>

        {/* chat */}
        <div className="ff-chat" ref={scroll}>
          {msgs.map((m, i) => (
            <div key={i} className={`ff-row ${m.who}`}>
              {m.who === "bot" && <div className="ff-av"><SoccerBall size={15} /></div>}
              <div className={`ff-bubble ${m.who}`}>
                {m.text && <div className="ff-text">{m.text}</div>}
                {m.recs && m.recs.length > 0 && (
                  <div className="ff-cards">
                    {m.recs.map((c: any, j: number) => (
                      <div key={j} className="ff-card">
                        <div className="ff-card-top">
                          <span className="ff-slot">{SLOT_LABEL[c.slot] || c.label}</span>
                          {c.confidence != null && <span className="ff-conf">{Math.round(c.confidence * 100)}% match</span>}
                        </div>
                        <div className="ff-name">{c.name}</div>
                        {c.why_locals_love_it && <div className="ff-why">❤️ {c.why_locals_love_it}</div>}
                        {!c.why_locals_love_it && (c.why_it_fits || [])[0] && <div className="ff-why">{(c.why_it_fits || [])[0]}</div>}
                        {c.review_quote && <div className="ff-quote">“{c.review_quote}”</div>}
                        {c.chain_comparison && <div className="ff-chain">🏆 “{c.chain_comparison.quote?.slice(0, 80)}…”</div>}
                        <div className="ff-tags">
                          {(c.matched_tags || []).slice(0, 3).map((t: string) => <span key={t} className="ff-tag">{t.replace(/_/g, " ")}</span>)}
                          {c.route_note && <span className="ff-route">📍 {c.route_note}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {m.venues && (
                  <div className="ff-cards">
                    {m.venues.map((v: any, j: number) => (
                      <div key={j} className="ff-card">
                        <div className="ff-slot">📺 {v.soccer_label?.replace(/_/g, " ")}</div>
                        <div className="ff-name">{v.name}</div>
                        <div className="ff-why">{v.note || "Fan gathering spot — confirm screenings before you go."}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="ff-row bot">
              <div className="ff-av"><SoccerBall size={15} className="ff-spin" /></div>
              <div className="ff-bubble bot"><div className="ff-typing"><i /><i /><i /></div></div>
            </div>
          )}
        </div>

        {/* quick chips (only at start) */}
        {msgs.length <= 1 && (
          <div className="ff-quick">
            {QUICK.map(q => <button key={q} className="ff-chip" onClick={() => send(q)}>{q}</button>)}
          </div>
        )}

        {/* input */}
        <div className="ff-input">
          <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === "Enter" && send()}
            placeholder="Ask FanFlow…  (any language)" />
          <button className="ff-send" onClick={() => send()} disabled={loading || !input.trim()} aria-label="send">
            <SoccerBall size={20} />
          </button>
        </div>
      </div>

      {/* settings sheet — Claude-mobile style, FanFlow/World-Cup themed */}
      {settings && (
        <div className="ff-sheet-bg" onClick={() => setSettings(false)}>
          <div className="ff-sheet" onClick={e => e.stopPropagation()}>
            <div className="ff-sheet-grip" />
            <div className="ff-sheet-head"><SoccerBall size={22} /><span>FanFlow Settings</span></div>

            <div className="ff-sec">MATCH</div>
            <label className="ff-rowset">
              <span>⚽ Current match</span>
              <select value={eventId} onChange={e => setEventId(e.target.value)}>
                {events.map(e => <option key={e._id} value={e._id}>{e.team_home_name} vs {e.team_away_name}</option>)}
              </select>
            </label>
            <div className="ff-rowset"><span>🏟️ Venue</span><b>{ev?.venue_name || "Levi's Stadium"}</b></div>

            <div className="ff-sec">PRIVACY</div>
            <div className="ff-rowset"><span>🛡️ Identity-blind</span><span className="ff-pill on">Always on</span></div>
            <div className="ff-note">We never guess your nationality, ethnicity, or where you're from. Recommendations use only what you ask for + aggregate match context.</div>

            <div className="ff-sec">DATA</div>
            <div className="ff-rowset"><span>⭐ Reviews</span><b>Real Google reviews</b></div>
            <div className="ff-rowset"><span>🤖 Made-up content</span><span className="ff-pill off">Never</span></div>
            <div className="ff-note">Every recommendation is a real place from Google. Nothing fabricated — when we're not sure, we say so.</div>

            <div className="ff-sec">ABOUT</div>
            <div className="ff-note" style={{ marginTop: 4 }}>
              FanFlow helps World Cup fans find <b>real local spots</b> — and gives small neighborhood shops a fair shot against the big chains. Built for the 2026 FIFA World Cup.
            </div>
            <button className="ff-close" onClick={() => setSettings(false)}>Done</button>
          </div>
        </div>
      )}
    </div>
  );
}

const FF_CSS = `
.ff-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
  background:radial-gradient(120% 80% at 50% 0%, #14532d 0%, #0a2417 55%, #06140d 100%);
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
.ff-phone{position:relative;width:100%;max-width:400px;height:min(860px,94vh);background:#f3f5f4;
  border-radius:34px;overflow:hidden;display:flex;flex-direction:column;
  box-shadow:0 30px 80px rgba(0,0,0,.55),0 0 0 10px #0d1b12,0 0 0 12px #1f3d2a;}
.ff-status{display:flex;justify-content:space-between;align-items:center;padding:10px 22px 4px;font-size:12px;font-weight:700;color:#0d1b12;background:#fff;}
.ff-status-icons{display:flex;align-items:center;gap:6px;font-size:11px;letter-spacing:-2px;}
.ff-header{display:flex;align-items:center;justify-content:space-between;padding:8px 16px 12px;background:#fff;border-bottom:1px solid #e6eae8;}
.ff-brand{display:flex;align-items:center;gap:10px;}
.ff-logo{width:38px;height:38px;border-radius:12px;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,#16a34a,#0d9488);box-shadow:0 4px 12px rgba(22,163,74,.4);}
.ff-title{font-weight:800;font-size:17px;color:#0d1b12;letter-spacing:-.02em;}
.ff-sub{font-size:11px;color:#5b6b62;margin-top:-2px;}
.ff-menu{display:flex;flex-direction:column;gap:3px;align-items:center;justify-content:center;width:38px;height:38px;border:none;background:#eef2f0;border-radius:11px;cursor:pointer;padding:0;}
.ff-menu:active{background:#dde6e1;}
.ff-chat{flex:1;overflow-y:auto;padding:16px 14px 8px;display:flex;flex-direction:column;gap:14px;
  background:linear-gradient(#eef3f0,#f3f5f4),repeating-linear-gradient(0deg,transparent,transparent 46px,rgba(22,163,74,.04) 47px,transparent 48px);}
.ff-row{display:flex;gap:8px;align-items:flex-end;animation:ffin .25s ease;}
.ff-row.you{flex-direction:row-reverse;}
@keyframes ffin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.ff-av{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,#16a34a,#0d9488);display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 2px 6px rgba(0,0,0,.15);}
.ff-bubble{max-width:80%;padding:10px 13px;border-radius:18px;font-size:13.5px;line-height:1.45;}
.ff-bubble.bot{background:#fff;color:#1a2b22;border-bottom-left-radius:5px;box-shadow:0 1px 3px rgba(0,0,0,.07);}
.ff-bubble.you{background:linear-gradient(135deg,#16a34a,#15803d);color:#fff;border-bottom-right-radius:5px;box-shadow:0 2px 8px rgba(22,163,74,.35);}
.ff-text{white-space:pre-wrap;}
.ff-cards{display:flex;flex-direction:column;gap:8px;margin-top:8px;}
.ff-card{background:#f6faf8;border:1px solid #d9ece2;border-radius:13px;padding:9px 11px;}
.ff-card-top{display:flex;justify-content:space-between;align-items:center;}
.ff-slot{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:#0d9488;}
.ff-conf{font-size:10px;color:#8a9991;font-weight:600;}
.ff-name{font-weight:800;font-size:14px;color:#0d1b12;margin:2px 0;}
.ff-why{font-size:12px;color:#3c5247;}
.ff-quote{font-size:11px;color:#6b7d72;font-style:italic;margin-top:4px;border-left:2px solid #c9e6d6;padding-left:7px;line-height:1.4;}
.ff-chain{font-size:11.5px;color:#b45309;font-style:italic;margin-top:3px;}
.ff-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;align-items:center;}
.ff-tag{font-size:10px;font-weight:600;background:#dbeafe;color:#2563eb;padding:2px 7px;border-radius:999px;}
.ff-route{font-size:10.5px;color:#5b6b62;}
.ff-typing{display:flex;gap:4px;padding:3px 2px;}
.ff-typing i{width:7px;height:7px;border-radius:50%;background:#16a34a;animation:ffb 1s infinite;}
.ff-typing i:nth-child(2){animation-delay:.15s}.ff-typing i:nth-child(3){animation-delay:.3s}
@keyframes ffb{0%,60%,100%{opacity:.3;transform:translateY(0)}30%{opacity:1;transform:translateY(-4px)}}
.ff-spin{animation:ffspin 1s linear infinite;}@keyframes ffspin{to{transform:rotate(360deg)}}
.ff-quick{display:flex;gap:8px;overflow-x:auto;padding:6px 14px 10px;background:#f3f5f4;}
.ff-chip{flex-shrink:0;font-size:12px;font-weight:600;color:#15803d;background:#fff;border:1px solid #c9e6d6;border-radius:999px;padding:8px 13px;cursor:pointer;white-space:nowrap;}
.ff-chip:active{background:#eafaf1;}
.ff-input{display:flex;gap:8px;padding:10px 12px 16px;background:#fff;border-top:1px solid #e6eae8;align-items:center;}
.ff-input input{flex:1;border:1px solid #d9ece2;background:#f6faf8;border-radius:22px;padding:11px 16px;font-size:14px;outline:none;color:#0d1b12;}
.ff-input input:focus{border-color:#16a34a;}
.ff-send{width:44px;height:44px;border-radius:50%;border:none;background:linear-gradient(135deg,#16a34a,#0d9488);display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;box-shadow:0 4px 12px rgba(22,163,74,.4);}
.ff-send:disabled{opacity:.45;box-shadow:none;}
.ff-send:active:not(:disabled){transform:scale(.94);}
.ff-sheet-bg{position:fixed;inset:0;background:rgba(6,20,13,.55);display:flex;align-items:flex-end;justify-content:center;z-index:50;animation:fffade .2s;}
@keyframes fffade{from{opacity:0}to{opacity:1}}
.ff-sheet{width:100%;max-width:400px;background:#fff;border-radius:24px 24px 34px 34px;padding:10px 20px 22px;max-height:80vh;overflow-y:auto;animation:ffup .28s cubic-bezier(.2,.9,.3,1);}
@keyframes ffup{from{transform:translateY(100%)}to{transform:none}}
.ff-sheet-grip{width:40px;height:5px;border-radius:3px;background:#d4ded8;margin:4px auto 14px;}
.ff-sheet-head{display:flex;align-items:center;gap:10px;font-size:18px;font-weight:800;color:#0d1b12;margin-bottom:10px;}
.ff-sec{font-size:11px;font-weight:800;letter-spacing:.06em;color:#94a39a;margin:16px 0 6px;}
.ff-rowset{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 13px;background:#f6faf8;border:1px solid #e6eae8;border-radius:12px;margin-bottom:6px;font-size:13.5px;color:#1a2b22;}
.ff-rowset select{border:none;background:none;font-size:13px;font-weight:600;color:#15803d;text-align:right;outline:none;max-width:170px;}
.ff-rowset b{color:#0d1b12;}
.ff-pill{font-size:11px;font-weight:800;padding:3px 10px;border-radius:999px;}
.ff-pill.on{background:#dcfce7;color:#16a34a;}
.ff-pill.off{background:#fee2e2;color:#dc2626;}
.ff-note{font-size:11.5px;color:#6b7d72;line-height:1.5;padding:0 4px;}
.ff-close{width:100%;margin-top:18px;padding:13px;border:none;border-radius:14px;background:linear-gradient(135deg,#16a34a,#15803d);color:#fff;font-weight:700;font-size:14px;cursor:pointer;}
@media(max-width:440px){.ff-wrap{padding:0}.ff-phone{max-width:100%;height:100vh;border-radius:0;box-shadow:none}}
`;
