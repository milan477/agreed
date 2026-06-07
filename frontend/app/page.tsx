"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, Goal, HomeData, Session, API_BASE } from "@/lib/api";

export default function HomePage() {
  const [home, setHome] = useState<HomeData | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState("");
  const [err, setErr] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  function fmtErr(e: unknown) {
    const msg = String(e instanceof Error ? e.message : e);
    if (msg.includes("404")) return "Backend needs restart: cd backend && ./run_dev.sh";
    if (msg.includes("500")) return "Backend error (likely disk/DB) — restart: cd backend && ./run_dev.sh";
    return msg;
  }

  async function refresh() {
    try {
      const h = await api.home();
      setHome(h);
      setErr("");
    } catch (e: any) {
      const msg = String(e.message || e);
      if (msg.includes("404")) {
        setErr("Backend is outdated — restart it: cd backend && ./run_dev.sh");
      } else {
        setErr(`Cannot reach API (${API_BASE}). Start backend: cd backend && ./run_dev.sh`);
      }
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [home?.chat_history]);

  async function send() {
    if (!input.trim() || busy) return;
    const userMsg = input.trim();
    setBusy(true);
    setErr("");
    setInput("");
    // Show user message immediately while the agent responds
    setHome((prev) =>
      prev
        ? { ...prev, chat_history: [...prev.chat_history, { role: "user", content: userMsg }] }
        : prev
    );
    try {
      await api.chat(userMsg, home?.chat_history ?? []);
      await refresh();
    } catch (e: any) {
      setErr(fmtErr(e));
    } finally {
      setBusy(false);
    }
  }

  async function joinInvite() {
    if (!invite.trim()) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.joinInvite(invite.trim());
      await refresh();
      window.location.href = `/session/${r.session.session_id}`;
    } catch (e: any) {
      setErr(fmtErr(e));
    } finally {
      setBusy(false);
    }
  }

  async function openGoal(goal: Goal) {
    setBusy(true);
    try {
      const r = await api.createSession({
        title: goal.title,
        kind: goal.kind,
        goal_id: goal.id,
        other_party_label: goal.other_party_label,
      });
      window.location.href = `/session/${r.session.session_id}`;
    } catch (e: any) {
      setErr(fmtErr(e));
      setBusy(false);
    }
  }

  const opportunities = mergeOpportunities(home);

  return (
    <>
      <header className="topbar">
        <div className="wrap topbar-inner">
          <div className="brand">
            <span className="name">agreed</span>
            <span className="motto">better agreements, faster</span>
          </div>
          {home && <span className="pill">Your ID: {home.user_id}</span>}
        </div>
      </header>

      <div className="wrap home-grid">
        {/* Left: chat with representation agent */}
        <section className="chat-panel">
          <div className="chat-head">
            <h2>Your agent</h2>
            <p>
              Chat naturally — your agent learns who you are and surfaces goals as you talk.
              Onboarding happens here, not in a separate flow.
            </p>
          </div>
          <div className="chat-msgs">
            {(home?.chat_history?.length ?? 0) === 0 && (
              <div className="msg agent">
                What are you trying to achieve? I can represent you in negotiations or
                community participations — tell me in your own words.
              </div>
            )}
            {home?.chat_history.map((m, i) => (
              <div key={i} className={`msg ${m.role === "user" ? "user" : "agent"}`}>{m.content}</div>
            ))}
            <div ref={bottom} />
          </div>
          <div className="chat-input">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="e.g. I want to buy custom printed shirts in bulk…"
              disabled={busy}
            />
            <button className="btn" onClick={send} disabled={busy || !input.trim()}>Send</button>
          </div>
        </section>

        {/* Right: opportunities + invitations */}
        <aside className="side-panel">
          <div className="card" style={{ padding: 16 }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 13 }}>Join invitation</h3>
            <div className="invite-row">
              <input
                value={invite}
                onChange={(e) => setInvite(e.target.value)}
                placeholder="Paste link or invite code"
              />
              <button className="btn subtle" onClick={joinInvite} disabled={busy}>Join</button>
            </div>
          </div>

          <div className="card" style={{ padding: 16, flex: 1 }}>
            <h3 style={{ margin: "0 0 4px", fontSize: 13 }}>Negotiate & participate</h3>
            <p className="hint" style={{ margin: "0 0 12px" }}>
              Goals from your chat and open sessions appear here.
            </p>
            {opportunities.length === 0 && (
              <p className="muted" style={{ fontSize: 13 }}>No goals yet — tell your agent what you want.</p>
            )}
            {opportunities.map((o) => (
              <OppCard key={o.key} item={o} onOpen={() => (o.session ? undefined : openGoal(o.goal!))} />
            ))}
          </div>

          {err && <div className="banner" style={{ background: "#fdecea", borderColor: "#f5c2c0", color: "#b3261e" }}>{err}</div>}
        </aside>
      </div>
    </>
  );
}

type Opp = { key: string; kind: string; title: string; meta: string; goal?: Goal; session?: Session };

function mergeOpportunities(home: HomeData | null): Opp[] {
  if (!home) return [];
  const seen = new Set<string>();
  const out: Opp[] = [];
  for (const g of home.goals) {
    if (seen.has(g.id)) continue;
    seen.add(g.id);
    const sess = home.sessions.find((s) => s.goal_id === g.id);
    out.push({
      key: g.id,
      kind: g.kind,
      title: g.title,
      meta: sess ? statusLabel(sess.status) : "From your chat — click to start",
      goal: g,
      session: sess,
    });
  }
  for (const s of home.sessions) {
    if (s.goal_id && seen.has(s.goal_id)) continue;
    out.push({
      key: s.session_id,
      kind: s.kind,
      title: s.title,
      meta: statusLabel(s.status),
      session: s,
    });
  }
  return out;
}

function statusLabel(s: string) {
  const m: Record<string, string> = {
    setup: "Set up rules",
    waiting: "Waiting for parties",
    ready: "Ready to run",
    running: "Negotiating…",
    review: "Review & sign",
    signed: "Signed",
  };
  return m[s] ?? s;
}

function OppCard({ item, onOpen }: { item: Opp; onOpen?: () => void }) {
  const href = item.session ? `/session/${item.session.session_id}` : undefined;
  const inner = (
    <>
      <div className="kind">{item.kind}</div>
      <div className="title">{item.title}</div>
      <div className="meta">{item.meta}</div>
    </>
  );
  if (href) {
    return <Link href={href} className={`opp-card ${item.kind}`}>{inner}</Link>;
  }
  return (
    <div className={`opp-card ${item.kind}`} onClick={onOpen} role="button" tabIndex={0}>
      {inner}
    </div>
  );
}
