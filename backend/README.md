# agreed — backend

Negotiation engine, multi-agent orchestration, observability, self-improvement,
evals, and the HTTP API.

## Architecture

```
agreed/
  config.py            Settings + capability auto-detection (graceful fallbacks)
  observability.py     Weave wiring (@op) + always-on local tracer + trace context
  llm.py               Pluggable LLM client: OpenAI / W&B Inference / heuristic
  domain/
    term_sheets.py     Scenario + private term sheets (priorities, limits, weights)
    scoring.py         Per-party utility, joint surplus, Pareto dominance
    frameworks.py      Moderation frameworks: pareto | rawlsian | rules
  agents/
    base.py            A2A message format + plug-in capability eval gate
    representation.py   (1) onboarding interview + (2.5) negotiation brief
    negotiator.py      Per-party negotiator (LLM policy + heuristic policy)
    moderator.py       Enforces framework, builds Pareto frontier, picks settlement
    researcher.py      Exa web research (stub fallback)
    critic.py          Scores proposals against both utility functions
    self_improve.py    Reads traces (W&B MCP) + optimizes strategy via self-play/DSPy
  sandbox/runner.py    One E2B sandbox per agent (local fallback)
  orchestration/
    engine.py          Pure negotiation loop (used for fast self-play rollouts)
    graph.py           LangGraph state machine: prep → turns → settle
  memory/store.py      Redis (session/cache/vector) + Mem0 (long-term) + fallbacks
  persistence/store.py User-scoped SQLite/Postgres store + audit log (RLS-ready)
  evals/evaluations.py Closure / utility / Pareto / fairness / bias evals
  api/server.py        FastAPI surface for the UI
  scripts/             Runnable demos
```

## The five+ agent roles (all traced in Weave)

1. **Representation** — learns the user, writes intent summary + brief.
2. **Negotiator** (one per party) — the main orchestrators of moves.
3. **Moderator** (optional) — enforces the framework, manages turns, proposes the
   optimal settlement on the Pareto frontier.
4. **Researcher** — gathers domain facts via Exa during prep.
5. **Critic** — scores proposals against each party's utility function.
6. **Self-improvement** — reads Weave traces and rewrites negotiator strategy.

All inter-agent messages use the A2A format (`agents/base.py`); all tool/LLM/agent
calls are wrapped with `@op` so they appear in Weave and the local trace view.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # core only; add ".[full]" for sponsor SDKs

python -m agreed.scripts.run_negotiation pareto       # one negotiation, full trace
python -m agreed.scripts.run_baseline_vs_improved     # headline: metric goes up
uvicorn agreed.api.server:app --reload                # API on :8000
```

Everything runs offline with deterministic heuristic agents. Set keys in `.env`
(see `../.env.example`) to light up real models, Weave, E2B, Exa, Redis, Mem0,
and Postgres — no code changes needed.

## The self-improvement loop (headline)

`SelfImprovementAgent`:
1. `read_traces()` — inspects prior Weave traces (W&B MCP server when configured,
   else the local tracer) to diagnose weak play.
2. `optimize_strategy()` — coordinate-ascent over `StrategyParams`
   (`concession_rate`, `acceptance_threshold`, `threshold_decay`, …) scored by
   fast self-play rollouts against the utility metric. DSPy is used to optimize the
   LLM prompt when available; the search is the offline workhorse.
3. The "after" run uses the improved strategy and beats baseline on the eval
   dashboard (typically **+8 buyer utility** on the default scenario).

## Data isolation

Every record is namespaced by `user_id` via `UserScopedStore`; there is no API to
read across users. Every access writes to an append-only `audit_log`. On Postgres,
enable the included `POSTGRES_RLS_SQL` row-level-security policy for DB-layer
enforcement too.
