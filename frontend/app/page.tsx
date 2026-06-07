"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, Goal, HomeData, Session, Connector, Intent, API_BASE } from "@/lib/api";

type ChatMsg = { role: string; content: string };

export default function HomePage() {
  const [home, setHome] = useState<HomeData | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [chatBusy, setChatBusy] = useState(false);
  const [invite, setInvite] = useState("");
  const [err, setErr] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // A suggested chip that trails off ("…" or "...") is a template to complete,
  // so it prefills the box and focuses; a complete answer sends straight away.
  const handleChip = (q: string) => {
    if (/(…|\.\.\.)\s*$/.test(q)) {
      setInput(q.replace(/(…|\.\.\.)\s*$/, "").trimEnd() + " ");
      inputRef.current?.focus();
    } else {
      sendMessage(q);
    }
  };

  const [extraMsgs, setExtraMsgs] = useState<ChatMsg[]>([]);
  const [intent, setIntent] = useState<Intent | null>(null);
  const [suggested, setSuggested] = useState<string[]>([]);
  const [followupNote, setFollowupNote] = useState("");
  const [voiceOn, setVoiceOn] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(false);

  const [contactPhone, setContactPhone] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [preferredChannel, setPreferredChannel] = useState<"text" | "call" | "auto">("text");
  const [outreachEnabled, setOutreachEnabled] = useState(true);
  const [caps, setCaps] = useState<Record<string, string>>({});
  const [weaveUrl, setWeaveUrl] = useState<string | null>(null);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [connected, setConnected] = useState<string[]>([]);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);

  const accountType = home?.profile?.account_type ?? "individual";
  const isCorp = accountType === "corporation";

  function fmtErr(e: unknown) {
    const msg = String(e instanceof Error ? e.message : e);
    if (msg.includes("503")) return "Set DATABASE_URL in .env to your Supabase Postgres connection string, then restart the backend.";
    if (msg.includes("404")) return "Backend needs restart: cd backend && ./run_dev.sh";
    if (msg.includes("500")) return "Backend error (likely disk/DB) — restart: cd backend && ./run_dev.sh";
    return msg;
  }

  async function refresh() {
    try {
      const h = await api.home();
      setHome(h);
      setContactPhone(h.profile.phone ?? "");
      setContactEmail(h.profile.email ?? "");
      setPreferredChannel(h.profile.preferred_channel ?? "text");
      setOutreachEnabled(h.profile.outreach_enabled !== false);
      setActiveConvId(h.active_conversation_id ?? null);
      setErr("");
    } catch (e: unknown) {
      const msg = String(e instanceof Error ? e.message : e);
      if (msg.includes("404")) setErr("Backend is outdated — restart it: cd backend && ./run_dev.sh");
      else setErr(`Cannot reach API (${API_BASE}). Start backend: cd backend && ./run_dev.sh`);
    }
  }

  async function loadConnectors() {
    try {
      const r = await api.connectors();
      setConnectors(r.connectors);
      setConnected(r.connected);
    } catch {
      /* backend may be warming up */
    }
  }

  useEffect(() => {
    refresh();
    loadConnectors();
    api.health().then((h) => {
      setCaps(h.capabilities ?? {});
      setWeaveUrl(h.weave_url ?? null);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [home?.chat_history, extraMsgs]);

  // The CopilotKit copilot can act on the user's behalf (open a negotiation,
  // connect an app, text someone); refresh the UI when it does.
  useEffect(() => {
    const onRefresh = () => {
      refresh();
      loadConnectors();
    };
    window.addEventListener("agreed:refresh", onRefresh);
    return () => window.removeEventListener("agreed:refresh", onRefresh);
  }, []);

  async function switchAccountType(next: "individual" | "corporation") {
    if (next === accountType) return;
    setBusy(true);
    try {
      await api.setAccountType(next);
      await refresh();
    } catch (e) {
      setErr(fmtErr(e));
    } finally {
      setBusy(false);
    }
  }

  async function startNewConversation() {
    if (chatBusy) return;
    setChatBusy(true);
    setErr("");
    setIntent(null);
    setSuggested([]);
    setFollowupNote("");
    try {
      const r = await api.createConversation();
      setActiveConvId(r.conversation.conversation_id);
      await refresh();
    } catch (e) {
      setErr(fmtErr(e));
    } finally {
      setChatBusy(false);
    }
  }

  async function switchConversation(conversationId: string) {
    if (chatBusy || conversationId === activeConvId) return;
    setChatBusy(true);
    setErr("");
    setIntent(null);
    setSuggested([]);
    setFollowupNote("");
    try {
      await api.activateConversation(conversationId);
      setActiveConvId(conversationId);
      await refresh();
    } catch (e) {
      setErr(fmtErr(e));
    } finally {
      setChatBusy(false);
    }
  }

  async function sendMessage(text?: string) {
    const userMsg = (text ?? input).trim();
    if (!userMsg) {
      setErr("Type a message first.");
      return;
    }
    if (chatBusy) return;
    setChatBusy(true);
    setErr("");
    setInput("");
    setSuggested([]);
    const priorHistory = home?.chat_history ?? [];
    setHome((prev) =>
      prev
        ? { ...prev, chat_history: [...prev.chat_history, { role: "user", content: userMsg }] }
        : {
            user_id: "…",
            profile: { intent_summary: "", style: "balanced", constraints: "", goals: [] },
            chat_history: [{ role: "user", content: userMsg }],
            goals: [],
            sessions: [],
            contacts: [],
          }
    );
    try {
      const convId = activeConvId ?? home?.active_conversation_id;
      const res = await api.chat(userMsg, priorHistory, convId);
      if (res.conversation_id) setActiveConvId(res.conversation_id);
      setIntent(res.intent && res.intent.detected ? res.intent : null);
      setSuggested(res.suggested_questions ?? []);
      if (res.followup_scheduled) {
        const ch = res.followup_scheduled.channel === "call" ? "call" : "text";
        setFollowupNote(`Follow-up ${ch} scheduled — your agent will reach out shortly.`);
      }
      if (speakReplies && typeof window !== "undefined" && window.speechSynthesis) {
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(res.reply);
        u.rate = 1;
        window.speechSynthesis.speak(u);
      }
      await refresh();
    } catch (e: unknown) {
      setErr(fmtErr(e));
    } finally {
      setChatBusy(false);
    }
  }

  async function joinInvite() {
    if (!invite.trim()) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.joinInvite(invite.trim());
      window.location.href = `/session/${r.session.session_id}`;
    } catch (e) {
      setErr(fmtErr(e));
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
    } catch (e) {
      setErr(fmtErr(e));
      setBusy(false);
    }
  }

  async function confirmIntent() {
    if (!intent || !intent.detected) return;
    const goal = home?.goals.find((g) => g.id === intent.goal_id);
    if (goal) {
      await openGoal(goal);
    } else {
      await openGoal({ id: intent.goal_id, title: intent.summary, kind: intent.kind, status: "open" } as Goal);
    }
  }

  async function connect(id: string) {
    setConnecting(id);
    try {
      const r = await api.connect(id);
      setConnected(r.profile.connections ?? []);
      if (r.learned?.agent_line) setExtraMsgs((m) => [...m, { role: "agent", content: r.learned.agent_line }]);
      await refresh();
    } catch (e) {
      setErr(fmtErr(e));
    } finally {
      setConnecting(null);
    }
  }

  async function saveContact() {
    setBusy(true);
    try {
      await api.updateContact({
        phone: contactPhone,
        email: contactEmail,
        preferred_channel: preferredChannel,
        outreach_enabled: outreachEnabled,
      });
      await refresh();
    } catch (e) {
      setErr(fmtErr(e));
    } finally {
      setBusy(false);
    }
  }

  function startVoiceInput() {
    if (typeof window === "undefined") return;
    const W = window as Window & { webkitSpeechRecognition?: typeof SpeechRecognition; SpeechRecognition?: typeof SpeechRecognition };
    const SR = W.SpeechRecognition || W.webkitSpeechRecognition;
    if (!SR) {
      setErr("Voice input is not supported in this browser.");
      return;
    }
    setVoiceOn(true);
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (ev) => {
      const text = ev.results[0]?.[0]?.transcript ?? "";
      if (text.trim()) sendMessage(text.trim());
    };
    rec.onerror = () => setVoiceOn(false);
    rec.onend = () => setVoiceOn(false);
    rec.start();
  }

  const opportunities = mergeOpportunities(home);
  const counterparties = home?.profile?.counterparties ?? [];

  return (
    <>
      <header className="topbar">
        <div className="wrap topbar-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true" />
            <span className="name">Agreed.</span>
            <span className="motto">better agreements, faster</span>
          </div>
          <div className="topbar-right">
            <div className="acct-toggle" role="tablist" aria-label="Account type">
              <button type="button" className={!isCorp ? "active" : ""} onClick={() => switchAccountType("individual")} disabled={busy}>
                Individual
              </button>
              <button type="button" className={isCorp ? "active" : ""} onClick={() => switchAccountType("corporation")} disabled={busy}>
                Corporation
              </button>
            </div>
            {home && <span className="pill">ID: {home.user_id}</span>}
            {caps.weave && (
              <span className={`pill ${caps.weave === "live" ? "live" : ""}`}>
                Weave: {caps.weave}
              </span>
            )}
            {weaveUrl && (
              <a className="pill link-pill" href={weaveUrl} target="_blank" rel="noreferrer">
                Dashboard ↗
              </a>
            )}
          </div>
        </div>
      </header>

      <div className="wrap home-grid">
        {/* Left: chat with representation agent */}
        <section className="chat-panel">
          <div className="chat-head">
            <div className="chat-head-row">
              <div>
                <div className="eyebrow" style={{ marginBottom: 6 }}>Representation</div>
                <h2>Your agent</h2>
              </div>
              <button type="button" className="btn ghost conv-new" disabled={chatBusy} onClick={startNewConversation}>
                + New chat
              </button>
            </div>
            <p>
              {isCorp
                ? "Talk through the deal you want done. Your agent picks up your priorities and limits, then negotiates on your behalf."
                : "Just talk. Connect your apps and your agent learns who you are, speaks in your voice, and acts for you when you're ready."}
            </p>
          </div>
          <div className="chat-layout">
            {(home?.conversations?.length ?? 0) > 0 && (
              <aside className="conv-sidebar" aria-label="Past conversations">
                {home!.conversations!.map((c) => (
                  <button
                    key={c.conversation_id}
                    type="button"
                    className={`conv-item ${c.conversation_id === activeConvId ? "active" : ""}`}
                    disabled={chatBusy}
                    onClick={() => switchConversation(c.conversation_id)}
                  >
                    <span className="conv-title">{c.title}</span>
                    {c.preview && <span className="conv-preview">{c.preview}</span>}
                  </button>
                ))}
              </aside>
            )}
            <div className="chat-main">
              <div className="chat-msgs">
            {(home?.chat_history?.length ?? 0) === 0 && extraMsgs.length === 0 && (
              <div className="msg agent">
                {isCorp
                  ? "What deal are you trying to get done? Tell me the shape of it and what matters most."
                  : "What's on your mind? Tell me in your own words — or link an app on the right and I'll get up to speed on my own."}
              </div>
            )}
            {home?.chat_history.map((m, i) => (
              <div key={i} className={`msg ${m.role === "user" ? "user" : "agent"}`}>{m.content}</div>
            ))}
            {extraMsgs.map((m, i) => (
              <div key={`x-${i}`} className={`msg ${m.role === "user" ? "user" : "agent"}`}>{m.content}</div>
            ))}

            {intent && intent.detected && (
              <div className="intent-card">
                <div className="intent-head">
                  <span className="eyebrow">Confirm intent</span>
                  <span className="conf">{Math.round(intent.confidence * 100)}% sure</span>
                </div>
                <p className="intent-prompt">{intent.prompt}</p>
                <div className="row">
                  <button type="button" className="btn" disabled={chatBusy} onClick={confirmIntent}>Yes, set it up</button>
                  <button type="button" className="btn ghost" disabled={chatBusy} onClick={() => setIntent(null)}>Not now</button>
                </div>
              </div>
            )}
            <div ref={bottom} />
              </div>

              {suggested.length > 0 && (
                <div className="chips">
                  {suggested.map((q, i) => (
                    <button key={i} type="button" className="chip" disabled={chatBusy} onClick={() => handleChip(q)}>
                      {q}
                    </button>
                  ))}
                </div>
              )}

              {followupNote && <p className="hint" style={{ padding: "0 16px 8px" }}>{followupNote}</p>}

              <div className="chat-input">
                <button
                  type="button"
                  className={`btn ghost mic-btn ${voiceOn ? "active" : ""}`}
                  onClick={startVoiceInput}
                  disabled={chatBusy || voiceOn}
                  title="Voice input"
                  aria-label="Voice input"
                >
                  {voiceOn ? "…" : "🎤"}
                </button>
                <input
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      sendMessage();
                    }
                  }}
                  placeholder={isCorp ? "e.g. We need a 12-month supply contract for components…" : "e.g. I want to buy a used car for under $9k…"}
                  disabled={chatBusy}
                />
                <button type="button" className="btn send-btn" onClick={() => sendMessage()} disabled={chatBusy}>
                  {chatBusy ? "…" : "Send"}
                </button>
              </div>
              <label className="speak-toggle">
                <input type="checkbox" checked={speakReplies} onChange={(e) => setSpeakReplies(e.target.checked)} />
                Speak agent replies aloud
              </label>
              {!home && !err && <p className="hint" style={{ padding: "0 16px 12px" }}>Connecting to agent…</p>}
              {err && <p className="chat-err">{err}</p>}
            </div>
          </div>
        </section>

        {/* Right: opportunities + connections + reach-out + invitations */}
        <aside className="side-panel">
          {/* agreed? — opportunities */}
          <div className="card opportunities-card">
            <h3>agreed?</h3>
            <p className="hint" style={{ margin: "0 0 12px" }}>
              {isCorp
                ? "Deals from your conversation and apps. Open one to send your agent in — or join someone else's below."
                : "Things you might want handled. Open one when you're ready — or join an agreement someone invited you to below."}
            </p>
            {opportunities.length === 0 ? (
              <p className="muted" style={{ fontSize: 13, margin: 0 }}>Nothing here yet — talk to your agent, link an app, or join an invite below.</p>
            ) : (
              <div className="opp-list">
                {opportunities.map((o) => (
                  <OppCard
                    key={o.key}
                    item={o}
                    isCorp={isCorp}
                    onOpen={o.session || !o.goal ? undefined : () => openGoal(o.goal!)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Join an agreement — directly under agreed? */}
          <div className="card join-card">
            <h3>Join an agreement</h3>
            <p className="hint" style={{ margin: "0 0 12px" }}>
              Someone shared an invite link or code? Paste it here to join their negotiation.
            </p>
            <div className="invite-row">
              <input
                value={invite}
                onChange={(e) => setInvite(e.target.value)}
                placeholder="Paste link or invite code"
                disabled={busy}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    joinInvite();
                  }
                }}
              />
              <button type="button" className="btn subtle" onClick={joinInvite} disabled={busy || !invite.trim()}>
                Join
              </button>
            </div>
          </div>

          {/* Connections — the agent learns about you */}
          <div className="card" style={{ padding: 16 }}>
            <div className="eyebrow" style={{ marginBottom: 4 }}>Learn about me</div>
            <p className="hint" style={{ margin: "0 0 12px" }}>
              Link an app and your agent gets up to speed on its own — context, priorities, who to talk to.
            </p>
            <div className="conn-list">
              {connectors.map((c) => {
                const on = connected.includes(c.id);
                return (
                  <button
                    key={c.id}
                    type="button"
                    className={`conn-row ${on ? "on" : ""}`}
                    disabled={on || connecting === c.id}
                    onClick={() => connect(c.id)}
                  >
                    <span className="conn-icon" aria-hidden="true">{c.icon}</span>
                    <span className="conn-body">
                      <span className="conn-name">{c.name}</span>
                      <span className="conn-blurb">{c.blurb}</span>
                    </span>
                    <span className="conn-state">{on ? "Linked ✓" : connecting === c.id ? "…" : "Connect"}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Reach-out settings */}
          <div className="card" style={{ padding: 16 }}>
            <div className="eyebrow" style={{ marginBottom: 8 }}>Reach you by text or call</div>
            <label>Your phone (for auto follow-ups)</label>
            <input
              value={contactPhone}
              onChange={(e) => setContactPhone(e.target.value)}
              placeholder="+1 555 123 4567"
              disabled={busy}
            />
            <label>Email (optional)</label>
            <input
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              placeholder="you@example.com"
              disabled={busy}
            />
            <label>Preferred channel</label>
            <select
              value={preferredChannel}
              onChange={(e) => setPreferredChannel(e.target.value as "text" | "call" | "auto")}
              disabled={busy}
            >
              <option value="text">Text (SMS)</option>
              <option value="call">Voice call</option>
              <option value="auto">Auto (text or call)</option>
            </select>
            <label className="speak-toggle" style={{ marginTop: 10 }}>
              <input
                type="checkbox"
                checked={outreachEnabled}
                onChange={(e) => setOutreachEnabled(e.target.checked)}
              />
              Auto follow-up when the agent has a question
            </label>
            <div className="row pad-top">
              <button className="btn subtle" disabled={busy} onClick={saveContact}>Save contact</button>
            </div>
            {(home?.followups?.length ?? 0) > 0 && (
              <p className="hint pad-top">
                Pending: {home!.followups!.filter((f) => f.status === "pending").length} follow-up(s)
              </p>
            )}
            {counterparties.length > 0 && (
              <p className="hint" style={{ marginTop: 10 }}>Knows: {counterparties.slice(0, 3).join(", ")}</p>
            )}
          </div>
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
      meta: sess ? statusLabel(sess.status) : g.from_connector ? "Spotted by your agent — click to start" : "From your chat — click to start",
      goal: g,
      session: sess,
    });
  }
  for (const s of home.sessions) {
    if (s.goal_id && seen.has(s.goal_id)) continue;
    out.push({ key: s.session_id, kind: s.kind, title: s.title, meta: statusLabel(s.status), session: s });
  }
  return out;
}

function statusLabel(s: string) {
  const m: Record<string, string> = {
    setup: "Set up",
    agent: "Choose agent",
    probe: "Check-in",
    prepare: "Review brief",
    waiting: "Waiting for parties",
    ready: "Ready to run",
    running: "Negotiating…",
    review: "Review & sign",
    signed: "Signed",
  };
  return m[s] ?? s;
}

function OppCard({ item, isCorp, onOpen }: { item: Opp; isCorp: boolean; onOpen?: () => void }) {
  const href = item.session ? `/session/${item.session.session_id}` : undefined;
  const badge = isCorp ? "agreed?" : item.kind;
  const inner = (
    <>
      <div className="kind">{badge}</div>
      <div className="title">{item.title}</div>
      <div className="meta">{item.meta}</div>
    </>
  );
  const cls = `opp-card ${isCorp ? "negotiation" : item.kind}`;
  if (href) return <Link href={href} className={cls}>{inner}</Link>;
  return (
    <button type="button" className={cls} onClick={onOpen}>
      {inner}
    </button>
  );
}
