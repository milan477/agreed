# WeaveHacks 4 — Submission draft

Copy/paste into the Cerebral Valley submission form. Fill in `[brackets]`.

## Team

- **Team name:** `[your team name]`
- **Members:** `[Name 1]`, `[Name 2]`, …
- **GitHub:** https://github.com/milan477/agreed (public)
- **X / LinkedIn:** `[handles for social tags]`

## Summary (2–3 sentences)

**agreed** is a multi-agent negotiation platform where AI agents represent humans in deal-making and community decisions. Users chat (text or voice), approve intent at every step, and watch a swarm of specialized agents negotiate under a chosen fairness framework — with every LLM, tool, and agent-to-agent call traced in W&B Weave. A self-improvement loop reads Weave traces and optimizes negotiator strategy so the next deal measurably moves up-and-to-the-right on a 2D utility plot.

## What it does / why it's useful

Legal and business negotiations are slow, opaque, and biased toward whoever has better information. agreed turns agreement-finding into an **observable optimization problem**: representation agents learn your priorities, negotiators trade concessions under moderator rules (Pareto, Rawlsian, etc.), and you sign only what you approve. Useful for procurement, contracts, salary talks, and multi-stakeholder participation.

## How it's built

| Layer | Stack |
|-------|--------|
| **Orchestration** | LangGraph negotiation graph; conversational + structured modes |
| **Agent protocols** | Custom **A2A** message format (`agents/base.py`); plug-in agents gated by `capability_eval` |
| **MCP-style connectors** | Email, calendar, Notion, contacts (`integrations/connectors.py`) — swappable for live MCP |
| **Self-improvement** | Reads W&B traces → coordinate-ascent over strategy params via self-play rollouts (DSPy optional) |
| **Frontend** | Next.js + **CopilotKit / AG-UI** assistant popup |
| **Backend** | FastAPI, SQLite/Supabase Postgres, Twilio SMS/voice follow-ups |
| **Deploy** | Docker + Google Cloud Run |

### Multi-agent roles (all Weave-traced)

1. **Representation** — onboarding, brief, tone mirroring  
2. **Negotiator** (×2) — per-party concession strategy  
3. **Moderator** — framework enforcement (LangGraph)  
4. **Researcher** — Exa web research  
5. **Critic** — fairness / bias checks  
6. **Self-improvement** — trace-driven strategy optimization  

## Sponsor tools & how we used them

| Sponsor | Usage |
|---------|--------|
| **W&B Weave** (required) | `weave.init()` + `@op` on every agent/LLM/tool/A2A call; in-UI trace panel + link to hosted dashboard |
| **W&B Inference** | OpenAI-compatible LLM backend when `WANDB_API_KEY` set |
| **W&B MCP server** | Self-improvement agent reads project runs; `.vscode/mcp.json` configured for Cursor |
| **OpenAI** | Negotiator LLM, chat agent, CopilotKit runtime, Twilio voice speech loop |
| **CopilotKit / AG-UI** | In-app assistant popup (`Assistant.tsx` + `/api/copilotkit`) |
| **Redis** | Short-term session cache in chat (`memory/store.py`) |
| **Mem0** | Long-term user preference recall in chat |
| **E2B** | Per-agent code sandboxes (local fallback without key) |
| **Exa** | Researcher agent web search |
| **Twilio** | Auto SMS/voice follow-ups when agent needs more info |
| **Cursor** | Primary IDE for hackathon build |

## Demo video

- `[Link to <2 min screen recording]`  
- Suggested flow: see `DEMO.md` (onboard → negotiate → trace → self-improve → sign)

## Eligibility checklist

- [x] Public GitHub repo  
- [x] Built at WeaveHacks 4 (Jun 6–7 2026) — git history shows weekend commits  
- [x] W&B Weave integrated (`backend/agreed/observability.py`)  
- [ ] In-person demo (Saturday + Sunday)  
- [x] Team work primarily own  

## Prior work disclosure

`[If anything existed before the hackathon, list it here. Judges evaluate only weekend work.]`
