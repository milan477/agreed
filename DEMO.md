# agreed — 3-minute demo runbook

Maps directly to the Definition of Done. Everything runs offline; add sponsor keys
in `.env` to light up the hosted Weave dashboard and real models.

## 0. Start (30s before demo)

```bash
# Terminal 1 — API
cd backend && source .venv/bin/activate
uvicorn agreed.api.server:app --port 8000

# Terminal 2 — UI
cd frontend && pnpm dev          # http://localhost:3000
```

Optional CLI fallback if the UI isn't up — this alone shows the headline:

```bash
cd backend && source .venv/bin/activate
python -m agreed.scripts.run_negotiation        # full negotiation + trace
python -m agreed.scripts.run_baseline_vs_improved   # metric improves after self-improvement
```

## 1. The script (3 minutes)

| Time | Action | What the judges see |
|------|--------|---------------------|
| 0:00 | **Onboard** — type purpose + constraints, generate intent summary, approve | Agent customization; user approves before continuing |
| 0:30 | **Scope** — pick a moderation framework (Pareto / Rawlsian / Rules) | Swappable frameworks; scope agreement |
| 0:50 | **Prepare** — generate brief (research + ranked priorities + opening), approve | Self-improvement prep step; user approves the brief |
| 1:10 | **Negotiate** — run; watch the round-by-round transcript with reasoning | Multi-agent negotiation, moderator turn-taking, per-agent sandboxes |
| 1:50 | **Review** — utility plot + expandable plain-language trace + Weave link | Observability as a feature; trace visible to the user |
| 2:10 | **Self-improvement** — click "Run self-improvement"; deal moves up-and-to-the-right | **Headline**: measurable metric gain after the loop |
| 2:40 | **Sign** — review final terms, sign | Nothing binds without a human signature |

## 2. Eligibility checklist (call these out)

- **W&B Weave**: every agent/LLM/tool/A2A call is `@op`-traced. Pill in the header
  shows `Weave: live` when `WANDB_API_KEY` is set; the trace panel links to the
  hosted dashboard.
- **Multi-agent**: 6 roles (representation, 2× negotiator, moderator, researcher,
  critic, self-improvement) communicating over A2A.
- **Observable**: plain-language trace + expandable full reasoning + Weave link.
- **Sandboxed**: one E2B sandbox provisioned per agent (header shows `live` with an
  `E2B_API_KEY`, else local fallback — visible in the trace as `sandbox.start`).

## 3. Solved concerns to mention

- **Trust**: user approves intent summary, brief, and final terms; nothing binds
  without a signature.
- **Neutrality/bias**: system prompt forbids injected opinions; `bias_eval`
  reports utility divergence (≈ 0).
- **Equal performance**: both parties get the same base agent/template/tools;
  plug-in agents must pass `capability_eval` (A2A gate).
- **Optimization quality**: explicit numerical utility functions; moderator selects
  on the Pareto frontier; the 2D utility plot shows "up and to the right".
- **Data isolation**: row-scoping by `user_id` + append-only audit log; demo it by
  switching users (a second user sees zero records).

## 4. If a key is added live

Put it in `backend/.env`, restart uvicorn, and the matching header pill flips to
`live`. No code changes. Order of impact for the demo: `WANDB_API_KEY` (Weave
dashboard), `OPENAI_API_KEY`/`WANDB_API_KEY` (real negotiator reasoning),
`E2B_API_KEY` (real sandboxes).
