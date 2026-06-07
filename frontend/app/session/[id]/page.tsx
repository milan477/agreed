"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, Session } from "@/lib/api";
import { TracePanel } from "@/components/TracePanel";

type Phase = "party" | "rules" | "prepare" | "submit" | "waiting" | "live" | "sign";

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const [session, setSession] = useState<Session | null>(null);
  const [frameworks, setFrameworks] = useState<any[]>([]);
  const [contacts, setContacts] = useState<{ user_id: string; label: string }[]>([]);
  const [otherId, setOtherId] = useState("");
  const [otherLabel, setOtherLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [trace, setTrace] = useState<any>(null);
  const [signed, setSigned] = useState(false);

  async function load() {
    const r = await api.getSession(id);
    setSession(r.session);
    setContacts(r.contacts);
    if (r.session.other_party_id) setOtherId(r.session.other_party_id);
    if (r.session.other_party_label) setOtherLabel(r.session.other_party_label);
    if (r.session.negotiation_result?.trace_id) {
      setTrace(await api.trace(r.session.negotiation_result.trace_id));
    }
  }

  useEffect(() => {
    api.frameworks().then((f) => setFrameworks(f.frameworks));
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
        status: "rules",
      });
      setSession(r.session);
    } finally {
      setBusy(false);
    }
  }

  async function saveRules(patch: Record<string, unknown>) {
    setBusy(true);
    try {
      const r = await api.updateSession(id, { ...patch, status: "prepare" });
      setSession(r.session);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setBusy(true);
    try {
      const r = await api.submitAgent(id);
      setSession(r.session);
      if (r.session.negotiation_result?.trace_id) {
        setTrace(await api.trace(r.session.negotiation_result.trace_id));
      }
    } finally {
      setBusy(false);
    }
  }

  async function doSign() {
    const negId = session?.negotiation_result?.negotiation_id;
    if (!negId) return;
    setBusy(true);
    try {
      await api.sign(negId, "Signed", "Buyer");
      setSigned(true);
    } finally {
      setBusy(false);
    }
  }

  if (!session) {
    return (
      <div className="wrap session-layout">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  return (
    <>
      <header className="topbar">
        <div className="wrap topbar-inner">
          <Link href="/" className="brand">
            <span className="name">agreed</span>
          </Link>
          <span className={`pill ${session.kind === "negotiation" ? "live" : ""}`}>{session.kind}</span>
        </div>
      </header>

      <div className="wrap session-layout">
        <div className={`opp-card ${session.kind}`} style={{ marginBottom: 20, cursor: "default" }}>
          <div className="kind">{session.kind}</div>
          <div className="title">{session.title}</div>
          <div className="meta">Invite: /join/{session.invite_code}</div>
        </div>

        {/* Phase: other party (negotiation only) */}
        {phase === "party" && !isParticipation && (
          <div className="card">
            <div className="phase-label">Other party</div>
            <h2>Who are you negotiating with?</h2>
            <p className="sub">Enter their user ID or pick someone you have worked with before.</p>
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
              <button className="btn" disabled={!otherId || busy} onClick={saveParty}>Continue to rules</button>
            </div>
          </div>
        )}

        {/* Phase: rules */}
        {(phase === "rules") && (
          <div className="card">
            <div className="phase-label">Agreement process</div>
            <h2>Rules & framework</h2>
            {isParticipation && session.other_party_label && (
              <p className="banner">Participating with: {session.other_party_label}</p>
            )}
            <p className="sub">Both parties agree on how agents will converse and reach a settlement.</p>
            <label>Moderation framework</label>
            <div className="grid2">
              {frameworks.map((f) => (
                <div
                  key={f.key}
                  className="turn"
                  style={{
                    borderColor: session.framework === f.key ? "var(--accent)" : "var(--border)",
                    cursor: "pointer",
                  }}
                  onClick={() => setSession({ ...session, framework: f.key })}
                >
                  <strong>{f.name}</strong>
                  <div className="reason">{f.description}</div>
                </div>
              ))}
            </div>
            <label style={{ marginTop: 16 }}>Agent</label>
            <div className="row">
              <button
                type="button"
                className={`btn ${!session.use_custom_agent ? "" : "ghost"}`}
                onClick={() => setSession({ ...session, use_custom_agent: false })}
              >
                Platform agent (default)
              </button>
              <button
                type="button"
                className={`btn ${session.use_custom_agent ? "" : "ghost"}`}
                onClick={() => setSession({ ...session, use_custom_agent: true })}
              >
                Plug in my own (A2A)
              </button>
            </div>
            {session.use_custom_agent && (
              <>
                <label>A2A agent endpoint</label>
                <input
                  value={session.custom_agent_url || ""}
                  onChange={(e) => setSession({ ...session, custom_agent_url: e.target.value })}
                  placeholder="https://my-agent.example/a2a"
                />
              </>
            )}
            <div className="row pad-top">
              <button
                className="btn"
                disabled={busy}
                onClick={() =>
                  saveRules({
                    framework: session.framework,
                    use_custom_agent: session.use_custom_agent,
                    custom_agent_url: session.custom_agent_url || "",
                  })
                }
              >
                Continue to preparation
              </button>
            </div>
          </div>
        )}

        {/* Phase: prepare + submit */}
        {phase === "prepare" && (
          <div className="card">
            <div className="phase-label">Preparation</div>
            <h2>Prepare your agent</h2>
            <p className="sub">
              Your agent researches the domain and builds a negotiation brief from your profile.
              When every party has submitted, the iterative negotiate-review-followup loop begins.
            </p>
            <ul className="hint" style={{ paddingLeft: 18 }}>
              <li>Framework: {session.framework}</li>
              <li>Agent: {session.use_custom_agent ? "Custom (A2A)" : "Platform default"}</li>
              {!isParticipation && otherLabel && <li>Counterparty: {otherLabel}</li>}
            </ul>
            <div className="row pad-top">
              <button className="btn" disabled={busy} onClick={submit}>
                Submit my agent
              </button>
            </div>
            <p className="hint pad-top">
              Parties:{" "}
              {Object.entries(session.parties).map(([uid, p]) => (
                <span key={uid} style={{ marginRight: 8 }}>
                  {p.label} {p.submitted ? "(submitted)" : "(pending)"}
                </span>
              ))}
            </p>
          </div>
        )}

        {/* Phase: waiting */}
        {phase === "waiting" && (
          <div className="card center">
            <h2>Waiting for other parties</h2>
            <p className="sub status-wait">Share the invite link so they can join and submit their agent.</p>
            <code>/join/{session.invite_code}</code>
          </div>
        )}

        {/* Phase: live / review */}
        {(phase === "live" || phase === "sign") && session.negotiation_result && (
          <>
            <div className="card">
              <div className="phase-label">Negotiation</div>
              <h2>
                {session.negotiation_result.outcome === "deal" ? "Deal reached" : "No deal"} in{" "}
                {session.negotiation_result.rounds} rounds
              </h2>
              {session.negotiation_result.score && (
                <div className="metrics">
                  <div className="metric">
                    <div className="k">Buyer</div>
                    <div className="v">{session.negotiation_result.score.buyer_score}</div>
                  </div>
                  <div className="metric">
                    <div className="k">Seller</div>
                    <div className="v">{session.negotiation_result.score.seller_score}</div>
                  </div>
                  <div className="metric">
                    <div className="k">Joint</div>
                    <div className="v">{session.negotiation_result.score.joint_surplus}</div>
                  </div>
                </div>
              )}
              <div className="pad-top">
                {session.negotiation_result.transcript.map((t) => (
                  <div className="turn" key={t.round}>
                    <div className="head">
                      <span className={`tag ${t.actor.toLowerCase()}`}>{t.actor}</span>
                      <span className="terms">
                        ${t.terms.price.toLocaleString()} · {t.terms.delivery_weeks}w · {t.terms.payment_terms}
                      </span>
                    </div>
                    <div className="reason">{t.my_reasoning}</div>
                  </div>
                ))}
              </div>
            </div>

            {trace && (
              <div className="card">
                <h2>Trace</h2>
                <TracePanel trace={trace} />
              </div>
            )}

            {phase === "sign" && (
              <div className="card">
                <h2>Sign agreement</h2>
                <p className="sub">Nothing binds without your explicit signature.</p>
                {!signed ? (
                  <button className="btn" disabled={busy} onClick={doSign}>Sign</button>
                ) : (
                  <div className="banner">Signed. Awaiting counterparty if needed.</div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

function derivePhase(s: Session | null): Phase {
  if (!s) return "party";
  if (s.status === "review") return "sign";
  if (s.status === "running" || s.negotiation_result) return "live";
  if (s.status === "waiting") return "waiting";
  if (s.status === "prepare") return "prepare";
  if (s.kind === "participation") return "rules";
  if (s.status === "setup" && !s.other_party_id) return "party";
  return "rules";
}
