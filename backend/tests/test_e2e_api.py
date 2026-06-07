"""End-to-end API integration tests for the agreed platform."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000"


def req(method: str, path: str, user: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-User-Id": user},
    )
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise AssertionError(f"{method} {path} -> {e.code}: {e.read().decode()}") from e


def main() -> int:
    user_a = "test_a_e2e"
    user_b = "test_b_e2e"
    passed = failed = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if cond:
            print(f"  PASS  {name}")
            passed += 1
        else:
            print(f"  FAIL  {name}  {detail}")
            failed += 1

    print("=== agreed E2E tests ===\n")

    # 1. Health
    print("1. Health & meta")
    h = req("GET", "/api/health", user_a)
    check("health ok", h["status"] == "ok")
    fw = req("GET", "/api/frameworks", user_a)
    check("3+ frameworks", len(fw["frameworks"]) >= 3)

    # 2. Home
    print("\n2. Home")
    home = req("GET", "/api/home", user_a)
    check("home has profile", "profile" in home)
    check("home has goals list", "goals" in home)

    # 3. Chat
    print("\n3. Chat & goal extraction")
    chat = req("POST", "/api/chat", user_a, {"message": "I want to buy custom printed shirts in bulk for my company"})
    check("chat reply", bool(chat.get("reply")))
    goals = chat["profile"]["goals"]
    check("goal extracted", len(goals) >= 1, f"goals={goals}")
    goal = goals[0]
    check("goal is negotiation", goal["kind"] == "negotiation")

    # 4. Chat history persisted
    home2 = req("GET", "/api/home", user_a)
    check("chat history saved", len(home2["chat_history"]) >= 2)

    # 5. Negotiation session
    print("\n4. Negotiation session")
    sess = req("POST", "/api/sessions", user_a, {
        "title": goal["title"], "kind": "negotiation", "goal_id": goal["id"],
    })
    sid = sess["session"]["session_id"]
    invite = sess["session"]["invite_code"]
    check("session created", bool(sid))
    check("session status setup", sess["session"]["status"] == "setup")

    # 6. Get session
    detail = req("GET", f"/api/sessions/{sid}", user_a)
    check("get session", detail["session"]["session_id"] == sid)

    # 7. Other party
    print("\n5. Other party & rules")
    patched = req("PATCH", f"/api/sessions/{sid}", user_a, {
        "other_party_id": user_b,
        "other_party_label": "Shirt Vendor Co",
        "framework": "rawlsian",
        "status": "prepare",
    })
    check("party set", patched["session"]["other_party_id"] == user_b)
    check("framework set", patched["session"]["framework"] == "rawlsian")

    # 8. Participation
    print("\n6. Participation session")
    part = req("POST", "/api/sessions", user_a, {
        "title": "City park redesign",
        "kind": "participation",
        "other_party_label": "Municipality",
    })
    psid = part["session"]["session_id"]
    check("participation status rules", part["session"]["status"] == "rules")
    check("participation host known", part["session"]["other_party_label"] == "Municipality")

    # 9. Join invite
    print("\n7. Invitation join")
    joined = req("POST", "/api/invitations/join", user_b, {"link": f"/join/{invite}"})
    check("user B in parties", user_b in joined["session"]["parties"])

    # 10. Submit negotiation
    print("\n8. Submit & negotiate")
    sub = req("POST", f"/api/sessions/{sid}/submit", user_a, {})
    result = sub["session"].get("negotiation_result")
    check("deal reached", result and result["outcome"] == "deal", str(result))
    check("has score", result and result["score"] is not None)
    check("has transcript", result and len(result["transcript"]) > 0)
    check("session review status", sub["session"]["status"] == "review")
    trace_id = result["trace_id"]

    # 11. Trace
    print("\n9. Trace")
    trace = req("GET", f"/api/trace/{trace_id}", user_a)
    check("trace spans", trace["span_count"] > 0)
    check("trace steps", len(trace["steps"]) > 0)

    # 12. Self-improve
    print("\n10. Self-improvement")
    si = req("POST", "/api/self-improve", user_a, {"party": "Buyer"})
    opt = si["optimization"]
    check("improvement > 0", opt["improvement"] > 0, str(opt))

    # 13. Evals
    print("\n11. Evals")
    ev = req("GET", "/api/evals?n=2", user_a)
    check("closure rate", ev["deal_closure_rate"] == 1.0)
    check("bias zero", ev["bias_divergence"] == 0.0)

    # 14. Isolation
    print("\n12. Data isolation")
    ra = req("GET", "/api/records", user_a)
    rb = req("GET", "/api/records", user_b)
    check("user A has records", len(ra["records"]) > 0)
    check("users isolated", len(ra["records"]) != len(rb["records"]) or user_a != user_b)

    # 15. Participation submit
    print("\n13. Participation submit")
    req("PATCH", f"/api/sessions/{psid}", user_a, {"status": "prepare"})
    psub = req("POST", f"/api/sessions/{psid}/submit", user_a, {})
    check("participation deal", psub["session"].get("negotiation_result") is not None)

    # 16. Sign (legacy endpoint)
    print("\n14. Sign")
    neg_id = sub["session"]["negotiation_result"].get("negotiation_id")
    if not neg_id:
        # negotiation stored separately - use session ref
        recs = [r for r in ra["records"] if r["kind"] == "negotiation"]
        neg_id = recs[0]["id"] if recs else None
    if neg_id:
        sign = req("POST", "/api/agreement/sign", user_a, {
            "negotiation_id": neg_id, "signature": "Alice", "party": "Buyer",
        })
        check("sign ok", sign.get("agreement_id") is not None)
    else:
        check("sign ok", False, "no negotiation_id")

    # 17. Participation chat goal
    print("\n15. Participation goal from chat")
    chat2 = req("POST", "/api/chat", user_a, {"message": "I want to participate in the community survey about park redesign"})
    kinds = [g["kind"] for g in chat2["profile"]["goals"]]
    check("participation goal", "participation" in kinds, str(kinds))

    print(f"\n=== {passed} passed, {failed} failed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
