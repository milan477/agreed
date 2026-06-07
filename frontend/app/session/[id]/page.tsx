"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, Session, Targets, Viewpoint } from "@/lib/api";

type Phase = "party" | "agent" | "probe" | "prepare" | "waiting" | "live" | "sign";

type DimMeta = {
  key: string;
  label: string;
  unit: string;
  step: number;
  better: string;
};

const DIMS: DimMeta[] = [
  { key: "price", label: "Price", unit: "$", step: 500, better: "you want this low" },
  { key: "delivery_weeks", label: "Delivery", unit: "wks", step: 1, better: "sooner is better" },
  { key: "warranty_months", label: "Warranty", unit: "mo", step: 1, better: "longer is better" },
  { key: "support_hours", label: "Support", unit: "h", step: 10, better: "more is better" },
];

const PAYMENT_TERMS = ["net30", "net40", "net50", "net60", "net70", "net80", "net90"];

function inputValue(value: number | string | undefined | null): string | number {
  return value ?? "";
}

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const [session, setSession] = useState<Session | null>(null);
  const [contacts, setContacts] = useState<{ user_id: string; label: string }[]>([]);
  const [otherId, setOtherId] = useState("");
  const [otherLabel, setOtherLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [externalUrl, setExternalUrl] = useState("");
  const [signed, setSigned] = useState(false);
  const [copied, setCopied] = useState(false);

  const joinUrl =
    session && typeof window !== "undefined"
      ? `${window.location.origin}/join/${session.invite_code}`
      : session
      ? `/join/${session.invite_code}`
      : "";

  function copyJoinLink() {
    if (!joinUrl) return;
    navigator.clipboard?.writeText(joinUrl).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      },
      () => undefined,
    );
  }

  // Probe-step working state
  const [mode, setMode] = useState<"structured" | "textual">("structured");
  const [targets, setTargets] = useState<Targets>({});
  const [viewpoints, setViewpoints] = useState<Viewpoint[]>([]);

  async function load() {
    const r = await api.getSession(id);
    setSession(r.session);
    setContacts(r.contacts);
    if (r.session.other_party_id) setOtherId(r.session.other_party_id);
    if (r.session.other_party_label) setOtherLabel(r.session.other_party_label);
    if (r.session.custom_agent_url) setExternalUrl(r.session.custom_agent_url);
    if (r.session.interaction_mode) setMode(r.session.interaction_mode);
    if (r.session.targets) setTargets(r.session.targets);
    if (r.session.viewpoints && r.session.viewpoints.length) setViewpoints(r.session.viewpoints);
  }

  useEffect(() => {
    load().catch(console.error);
  }, [id]);

  const phase = derivePhase(session);
  const isParticipation = session?.kind === "participation";

  async function saveParty() {
    if (!session) return;
    setBusy(true);
    try {
      const r = await api.updateSession(id, {
        other_party_id: otherId,
        other_party_label: otherLabel,
        status: "agent",
      });
      setSession(r.session);
    } finally {
      setBusy(false);
    }
  }

  async function chooseAgent(useCustom: boolean, url = "") {
    setBusy(true);
    try {
      const r = await api.chooseAgent(id, useCustom, url);
      setSession(r.session);
      if (r.session.targets) setTargets(r.session.targets);
      if (r.session.interaction_mode) setMode(r.session.interaction_mode);
    } finally {
      setBusy(false);
    }
  }

  async function submitProbe() {
    setPreparing(true);
    setBusy(true);
    try {
      const body = isParticipation
        ? { viewpoints, interaction_mode: "textual" }
        : { targets, interaction_mode: mode };
      const r = await api.saveProbe(id, body);
      setSession(r.session);
    } finally {
      setBusy(false);
      setPreparing(false);
    }
  }

  async function submit() {
    setBusy(true);
    try {
      const r = await api.submitAgent(id);
      setSession(r.session);
    } finally {
      setBusy(false);
    }
  }

  async function doSign() {
    const negId = session?.negotiation_result?.negotiation_id;
    if (!negId) return;
    setBusy(true);
    try {
      await api.sign(negId, "Signed", "You");
      setSigned(true);
    } finally {
      setBusy(false);
    }
  }

  function setDim(key: string, field: "target" | "walk_away" | "importance", value: number | string) {
    setTargets((prev) => ({ ...prev, [key]: { ...(prev[key] || {}), [field]: value } }));
  }

  if (!session) {
    return (
      <div className="wrap session-layout">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  const isCorp = session.account_type === "corporation";
  const badge = isCorp ? "agreed?" : session.kind;
  const result = session.negotiation_result;
  const visibleMessages = result?.messages?.filter((m) => m.side !== "them") ?? [];

  return (
    <>
      <header className="topbar">
        <div className="wrap topbar-inner">
          <Link href="/" className="brand">
            <span className="brand-mark" aria-hidden="true" />
            <span className="name">Agreed.</span>
          </Link>
          <span className={`pill ${session.kind === "negotiation" ? "live" : ""}`}>{badge}</span>
        </div>
      </header>

      <div className="wrap session-layout">
        <div className={`opp-card ${session.kind}`} style={{ marginBottom: 20, cursor: "default" }}>
          <div className="kind">{badge}</div>
          <div className="title">{session.title}</div>
          <div className="meta">Invite: /join/{session.invite_code}</div>
        </div>

        {/* Phase: other party (negotiation only) */}
        {phase === "party" && !isParticipation && (
          <div className="card">
            <div className="phase-label">Other party</div>
            <h2>Who's on the other side?</h2>
            <p className="sub">Enter their ID, or pick someone you've dealt with before. Leave the label as a name you'll recognise.</p>
            <label>Other party ID</label>
            <input value={otherId} onChange={(e) => setOtherId(e.target.value)} placeholder="e.g. u_abc123" />
            <label>Label (optional)</label>
            <input value={otherLabel} onChange={(e) => setOtherLabel(e.target.value)} placeholder="Acme Corp" />
            {contacts.length > 0 && (
              <>
                <label>Previously added</label>
                <div className="row pad-top">
                  {contacts.map((c) => (
                    <button
                      key={c.user_id}
                      type="button"
                      className={`party-chip ${otherId === c.user_id ? "selected" : ""}`}
                      onClick={() => { setOtherId(c.user_id); setOtherLabel(c.label); }}
                    >
                      {c.label} <span className="hint">({c.user_id})</span>
                    </button>
                  ))}
                </div>
              </>
            )}
            <div className="row pad-top">
              <button className="btn" disabled={!otherId || busy} onClick={saveParty}>Continue</button>
            </div>
          </div>
        )}

        {/* Phase: agent choice */}
        {phase === "agent" && (
          <div className="card">
            <div className="phase-label">Representation</div>
            <h2>Who acts for you here?</h2>
            {isParticipation && session.other_party_label && (
              <p className="banner">With: {session.other_party_label}</p>
            )}
            <p className="sub">
              Pick who represents you. Next, your agent will check a few things with you before it engages.
            </p>
            <div className="agent-choice-grid">
              <button
                type="button"
                className={`agent-choice ${!session.use_custom_agent ? "selected" : ""}`}
                disabled={busy}
                onClick={() => chooseAgent(false)}
              >
                <strong>Let my agent do it</strong>
                <span className="reason">
                  Your agreed agent — it already knows you from your conversation, speaks in your voice, and works the deal for you.
                </span>
              </button>
              <button
                type="button"
                className={`agent-choice ${session.use_custom_agent ? "selected" : ""}`}
                disabled={busy}
                onClick={() => setSession({ ...session, use_custom_agent: true })}
              >
                <strong>Plug in an external one</strong>
                <span className="reason">
                  Bring your own agent over A2A. It has to clear a quick capability check before it can take part.
                </span>
              </button>
            </div>
            {session.use_custom_agent && (
              <>
                <label>A2A agent endpoint</label>
                <input
                  value={externalUrl}
                  onChange={(e) => setExternalUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && externalUrl.trim()) chooseAgent(true, externalUrl.trim());
                  }}
                  placeholder="https://my-agent.example/a2a"
                />
                <div className="row pad-top">
                  <button
                    type="button"
                    className="btn"
                    disabled={busy || !externalUrl.trim()}
                    onClick={() => chooseAgent(true, externalUrl.trim())}
                  >
                    Connect
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* Phase: probe (targets / viewpoints + interaction mode) */}
        {phase === "probe" && (
          <div className="card">
            <div className="phase-label">Quick check-in</div>
            {isParticipation ? (
              <>
                <h2>What's your take?</h2>
                <p className="sub">
                  Tell your agent where you stand so it can argue your corner. Add the points that matter to you.
                </p>
                <ViewpointEditor viewpoints={viewpoints} setViewpoints={setViewpoints} />
              </>
            ) : (
              <>
                <h2>Before I go in — what are we aiming for?</h2>
                <p className="sub">
                  Set your target (what you'd love) and your walk-away (your hard line) for each point, and how
                  much each one matters. Your agent holds these privately and never reveals them.
                </p>

                <div className="mode-pick">
                  <span className="mode-label">How should the two agents talk?</span>
                  <div className="seg">
                    <button
                      type="button"
                      className={mode === "structured" ? "active" : ""}
                      onClick={() => setMode("structured")}
                    >
                      Structured offers
                    </button>
                    <button
                      type="button"
                      className={mode === "textual" ? "active" : ""}
                      onClick={() => setMode("textual")}
                    >
                      Free conversation
                    </button>
                  </div>
                  <p className="hint">
                    Both sides use the same format. The counterparty's agent has agreed to{" "}
                    <strong>{mode === "structured" ? "structured offers" : "a free conversation"}</strong>.
                  </p>
                </div>

                <div className="probe-grid">
                  {DIMS.map((d) => {
                    const t = targets[d.key] || {};
                    return (
                      <div key={d.key} className="probe-card">
                        <div className="probe-head">
                          <strong>{d.label}</strong>
                          <span className="hint">{d.better}</span>
                        </div>
                        <div className="probe-inputs">
                          <label>
                            Target
                            <div className="inline-num">
                              <span>{d.unit}</span>
                              <input
                                type="number"
                                value={inputValue(t.target)}
                                step={d.step}
                                onChange={(e) => setDim(d.key, "target", e.target.value === "" ? "" : Number(e.target.value))}
                              />
                            </div>
                          </label>
                          <label>
                            Walk-away
                            <div className="inline-num">
                              <span>{d.unit}</span>
                              <input
                                type="number"
                                value={inputValue(t.walk_away)}
                                step={d.step}
                                onChange={(e) => setDim(d.key, "walk_away", e.target.value === "" ? "" : Number(e.target.value))}
                              />
                            </div>
                          </label>
                        </div>
                        <div className="imp-row">
                          <span className="hint">Matters</span>
                          <div className="imp-dots">
                            {[1, 2, 3, 4, 5].map((n) => (
                              <button
                                key={n}
                                type="button"
                                className={`imp-dot ${Number(t.importance ?? 3) >= n ? "on" : ""}`}
                                onClick={() => setDim(d.key, "importance", n)}
                                aria-label={`importance ${n}`}
                              />
                            ))}
                          </div>
                        </div>
                      </div>
                    );
                  })}

                  <div className="probe-card">
                    <div className="probe-head">
                      <strong>Payment terms</strong>
                      <span className="hint">longer is better for you</span>
                    </div>
                    <select
                      className="pay-select"
                      value={String(targets.payment_terms?.target ?? "")}
                      onChange={(e) => setDim("payment_terms", "target", e.target.value)}
                    >
                      <option value="">Let my agent infer</option>
                      {PAYMENT_TERMS.map((p) => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                    <div className="imp-row">
                      <span className="hint">Matters</span>
                      <div className="imp-dots">
                        {[1, 2, 3, 4, 5].map((n) => (
                          <button
                            key={n}
                            type="button"
                            className={`imp-dot ${Number(targets.payment_terms?.importance ?? 3) >= n ? "on" : ""}`}
                            onClick={() => setDim("payment_terms", "importance", n)}
                            aria-label={`importance ${n}`}
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </>
            )}
            <div className="row pad-top">
              <button
                className="btn"
                disabled={busy || (isParticipation && viewpoints.filter((v) => v.stance || v.topic).length === 0)}
                onClick={submitProbe}
              >
                Looks right — prep my agent
              </button>
            </div>
            {preparing && <p className="hint pad-top">Researching and writing your brief…</p>}
          </div>
        )}

        {/* Phase: prepare + submit */}
        {phase === "prepare" && (
          <div className="card">
            <div className="phase-label">Your brief</div>
            <h2>Here's how I'll play it</h2>
            <p className="sub">
              I pulled this together from what you told me. Take a look — when you're happy, send me in.
            </p>
            {session.brief ? (
              <div className="grid2 pad-top">
                <div className="turn">
                  <h3>What I'll push for</h3>
                  <div className="reason">{session.brief.ranked_priorities?.join(" › ")}</div>
                  {session.brief.strategy && (
                    <>
                      <h3 style={{ marginTop: 12 }}>Approach</h3>
                      <div className="reason">{session.brief.strategy}</div>
                    </>
                  )}
                </div>
                <div className="turn">
                  <h3>{session.brief.research_heading || "Prep notes"}</h3>
                  {(session.brief.research_findings ?? []).map((f, i) => (
                    <div key={i} className="reason" style={{ marginBottom: 6 }}>· {f.snippet}</div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="muted">Brief not ready — go back and check in with your agent.</p>
            )}
            <ul className="hint pad-top" style={{ paddingLeft: 18 }}>
              <li>Representing you: {session.use_custom_agent ? "your external agent (A2A)" : "your agreed agent"}</li>
              {!isParticipation && (
                <li>Format: {session.interaction_mode === "textual" ? "free conversation" : "structured offers"}</li>
              )}
              {!isParticipation && otherLabel && <li>Other side: {otherLabel}</li>}
            </ul>
            <div className="row pad-top">
              <button className="btn" disabled={busy} onClick={submit}>
                {busy ? "Working…" : "Send my agent in"}
              </button>
            </div>
          </div>
        )}

        {/* Phase: waiting */}
        {phase === "waiting" && (
          <div className="card center">
            <h2>Share your agreed? link</h2>
            <p className="sub status-wait">
              Send this to the other party. When they open it, their agent joins and the two agents negotiate.
            </p>
            <div className="invite-row pad-top">
              <input readOnly value={joinUrl} onFocus={(e) => e.currentTarget.select()} />
              <button className="btn" onClick={copyJoinLink}>{copied ? "Copied" : "Copy link"}</button>
            </div>
          </div>
        )}

        {/* Phase: live / review */}
        {(phase === "live" || phase === "sign") && result && (
          <>
            <div className="card">
              <div className="phase-label">{result.mode === "textual" ? "Conversation" : "Negotiation"}</div>
              <h2>{result.outcome === "deal" ? "Agreement reached" : "No agreement"}{result.rounds ? ` · ${result.rounds} rounds` : ""}</h2>
              {result.summary && <p className="sub">{result.summary}</p>}

              {result.mode === "structured" && result.score && (
                <div className="metrics">
                  <div className="metric">
                    <div className="k">You</div>
                    <div className="v">{result.score.buyer_score}</div>
                  </div>
                </div>
              )}

              <div className="convo pad-top">
                {visibleMessages.length === 0 && (
                  <p className="muted" style={{ fontSize: 13 }}>
                    Counterparty-side transcript details are kept private. Showing only your agent's side.
                  </p>
                )}
                {visibleMessages.map((m, i) => (
                  <div key={i} className={`bubble-row ${m.side}`}>
                    <div className={`bubble ${m.side}`}>
                      <div className="bubble-head">
                        <span className="speaker">{m.speaker}</span>
                        {m.action === "accept" && <span className="accept-tag">accepts</span>}
                      </div>
                      <div className="bubble-text">{m.text}</div>
                      {m.terms && (
                        <div className="bubble-terms">
                          ${m.terms.price.toLocaleString()} · {m.terms.delivery_weeks}w · {m.terms.payment_terms} ·{" "}
                          {m.terms.warranty_months}mo · {m.terms.support_hours}h
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {phase === "sign" && (
              <div className="card">
                <h2>Sign off</h2>
                <p className="sub">Nothing's binding until you sign. Here's what was agreed:</p>
                <div className="agreement-box">{result.agreement_text || "See the conversation above."}</div>
                {!signed ? (
                  <button className="btn" disabled={busy} onClick={doSign}>Sign</button>
                ) : (
                  <div className="banner">Signed. Awaiting the other side if needed.</div>
                )}
              </div>
            )}
          </>
        )}

      </div>
    </>
  );
}

function ViewpointEditor({
  viewpoints,
  setViewpoints,
}: {
  viewpoints: Viewpoint[];
  setViewpoints: (v: Viewpoint[]) => void;
}) {
  const rows = viewpoints.length ? viewpoints : [{ topic: "", stance: "" }];
  function update(i: number, field: "topic" | "stance", value: string) {
    const next = rows.map((r, idx) => (idx === i ? { ...r, [field]: value } : r));
    setViewpoints(next);
  }
  function add() {
    setViewpoints([...rows, { topic: "", stance: "" }]);
  }
  function remove(i: number) {
    setViewpoints(rows.filter((_, idx) => idx !== i));
  }
  return (
    <div className="vp-list pad-top">
      {rows.map((r, i) => (
        <div key={i} className="vp-row">
          <input
            className="vp-topic"
            value={r.topic}
            onChange={(e) => update(i, "topic", e.target.value)}
            placeholder="Topic (e.g. Green space)"
          />
          <input
            className="vp-stance"
            value={r.stance}
            onChange={(e) => update(i, "stance", e.target.value)}
            placeholder="Your stance (e.g. keep the mature trees)"
          />
          {rows.length > 1 && (
            <button type="button" className="vp-del" onClick={() => remove(i)} aria-label="remove">×</button>
          )}
        </div>
      ))}
      <button type="button" className="btn subtle" onClick={add}>+ Add a point</button>
    </div>
  );
}

function derivePhase(s: Session | null): Phase {
  if (!s) return "party";
  if (s.status === "review") return "sign";
  if (s.status === "running" || s.negotiation_result) return "live";
  if (s.status === "waiting") return "waiting";
  if (s.status === "prepare") return "prepare";
  if (s.status === "probe") return "probe";
  if (s.kind === "participation" && (s.status === "rules" || s.status === "agent")) return "agent";
  if (s.status === "setup" && !s.other_party_id && s.kind === "negotiation") return "party";
  if (s.status === "rules" || s.status === "agent" || s.status === "setup") return "agent";
  return "prepare";
}
