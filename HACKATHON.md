# WeaveHacks 4 — eligibility & requirements checklist

Cross-reference for prize eligibility and submission. See also `SUBMISSION.md` for copy-paste submission text.

## Must-haves (prize eligibility)

| Requirement | Status | Where |
|-------------|--------|-------|
| Public GitHub repo | ✅ | https://github.com/milan477/agreed |
| Built at hackathon (Jun 6–7 2026) | ⚠️ Confirm | Git commit timestamps; disclose any pre-existing code in submission |
| W&B Weave used | ✅ | `backend/agreed/observability.py` — `weave.init()` + `@op` on all agents |
| In-person Sat + Sun | ⬜ | Attendance |
| Primarily your own work | ⬜ | Team confirmation |

## Weave integration (2 lines minimum)

```python
import weave
weave.init("entity/agreed")  # also via init_observability() on API startup
```

Every agent/LLM/tool call uses `@op(...)` from `observability.py`.

Set in `.env`:

```bash
WANDB_API_KEY=
WANDB_ENTITY=
WEAVE_PROJECT=agreed
```

Health check: `GET /api/health` → `"weave": "live"` and `weave_url` when configured.

## Judging criteria — how we address them

| Criterion | Our answer |
|-----------|------------|
| **Creativity** | Negotiation as observable multi-agent optimization with swappable fairness frameworks |
| **Harness sophistication** | 6+ specialized agents, LangGraph moderator, A2A plug-in gate, conversational + structured modes |
| **Utility** | Real pain: slow opaque negotiations → fast traced agreements with human approval gates |
| **Technical execution** | Full stack: FastAPI + Next.js + Weave + self-improve loop + Twilio outreach + Cloud Run deploy |
| **Sponsor usage** | Weave (required), OpenAI, CopilotKit/AG-UI, Redis, Mem0, E2B, Exa, Twilio |

## Submission deliverables (Cerebral Valley)

- [ ] Team name + all members (CV profile with email/socials)
- [ ] Public GitHub link
- [ ] Sponsor tool list (see `SUBMISSION.md`)
- [ ] 2–3 sentence summary + architecture description
- [ ] Demo video (<2 min) or screenshots
- [ ] X / LinkedIn handles

## 3-minute demo script

See `DEMO.md`. Headline moment: **self-improvement** — baseline vs improved utility on the plot.

## Sponsor keys to enable for live demo

Priority order:

1. `WANDB_API_KEY` — hosted Weave dashboard (required for eligibility display)
2. `OPENAI_API_KEY` — real negotiator reasoning + CopilotKit (`NEXT_PUBLIC_ENABLE_ASSISTANT=1`)
3. `E2B_API_KEY` — real sandboxes
4. `REDIS_URL` / `MEM0_API_KEY` — memory recall in chat
5. `TWILIO_*` + `PUBLIC_BASE_URL` — auto SMS/voice follow-ups

## W&B MCP in Cursor

`.vscode/mcp.json` includes the hosted W&B MCP server for trace inspection during self-improvement.
