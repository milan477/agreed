"""Run one negotiation end-to-end with the LangGraph orchestrator + Weave tracing.

    python -m agreed.scripts.run_negotiation [framework]

framework: pareto (default) | rawlsian | rules
"""

from __future__ import annotations

import sys

from ..agents.negotiator import format_deal, format_ranking
from ..config import capability_report
from ..observability import get_spans, init_observability, weave_trace_url
from ..orchestration.graph import NegotiationOrchestrator


def main() -> None:
    framework = sys.argv[1] if len(sys.argv) > 1 else "pareto"
    obs = init_observability()

    print("=" * 68)
    print("  agreed — negotiation run")
    print("=" * 68)
    for k, v in capability_report().items():
        print(f"  {k:18}: {v}")
    print(f"  weave init        : {obs}")
    print("-" * 68)

    orch = NegotiationOrchestrator(framework=framework, max_rounds=16)
    result = orch.run()

    for e in result.transcript:
        note = f"  [{e['moderator_note']}]" if e.get("moderator_note") else ""
        print(f"R{e['round']:2} [{e['actor']:6}] {e['action']:7} {format_deal(e['terms'])}{note}")
        print(f"        reasoning: {e['my_reasoning']}")
        print(f"        ranking:   {format_ranking(e['inferred_other_priorities'])}")

    print("-" * 68)
    print(f"Outcome: {result.outcome} in {result.rounds} rounds "
          f"({'accepted by ' + result.accepted_by if result.accepted_by else 'forced close'})")
    if result.score:
        s = result.score
        print(f"Buyer utility:  {s['buyer_score']}/100")
        print(f"Seller utility: {s['seller_score']}/100")
        print(f"Joint surplus:  {s['joint_surplus']}/200   (min utility {s['min_utility']})")
    if result.settlement and result.settlement.get("settlement_score"):
        ss = result.settlement
        print(f"Framework pick ({ss['framework_name']}): joint "
              f"{ss['settlement_score']['joint_surplus']} on frontier of {ss['frontier_size']}")
        if ss.get("improvement_available"):
            print(f"  Moderator: a better deal exists on the frontier: {format_deal(ss['settlement'])}")

    print("-" * 68)
    print(f"Trace id: {result.trace_id}  ({len(get_spans(result.trace_id))} spans recorded)")
    url = weave_trace_url()
    if url:
        print(f"Weave dashboard: {url}")


if __name__ == "__main__":
    main()
