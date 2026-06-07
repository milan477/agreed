# agreed

**better agreements, faster**

AI agents represent humans in negotiation and agreement-finding, reaching
optimal, transparent agreements inside a chosen moderation framework. Built for
WeaveHacks 4 (W&B hackathon). Theme: self-improving agents.

Agreeing is an optimization problem. `agreed` turns slow legal/negotiation
processes into fast, observable, optimally-balanced agent negotiations — with
every agent move traced in W&B Weave and visible to the user.

---

## What's here

```
backend/    Python: negotiation engine, 5 agent roles, LangGraph moderator,
            E2B sandboxes, Weave tracing, DSPy self-improvement, evals, FastAPI
frontend/   Next.js + CopilotKit minimal UI (onboarding, negotiation, trace, sign)
```

## Eligibility-critical features

- **W&B Weave** tracing on every agent / LLM / tool / A2A call
- **Multi-agent**: representation, negotiator (per party), moderator, researcher,
  critic, self-improvement
- **Observable**: plain-language trace + linkable Weave dashboard
- **Sandboxed**: one E2B sandbox per agent (local fallback when no key)

## Quick start (backend)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Optional: copy and fill in keys. Everything runs offline without them.
cp ../.env.example .env

# Run a negotiation end-to-end (offline-safe heuristic agents by default)
python -m agreed.scripts.run_negotiation

# Headline demo: baseline vs self-improved run, metric goes up
python -m agreed.scripts.run_baseline_vs_improved

# API server
uvicorn agreed.api.server:app --reload
```

## Quick start (frontend)

```bash
cd frontend
pnpm install
pnpm dev   # http://localhost:3000
```

## Design principles

- **You are always in control.** You approve the intent summary, the negotiation
  brief, and the final agreement. Nothing binds without a human signature.
- **Trace visibility is a feature**, not a debug tool.
- **Neutrality**: agents represent the user; no injected opinions. Bias eval
  checks output divergence under swapped demographics.
- **Strict data isolation**: row-level isolation by `user_id`, every access audited.

See `backend/README.md` for architecture and the self-improvement loop.

## Hackathon (WeaveHacks 4)

- **Eligibility checklist:** `HACKATHON.md`
- **Submission copy-paste:** `SUBMISSION.md`
- **3-min demo script:** `DEMO.md`
