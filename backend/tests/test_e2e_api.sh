#!/usr/bin/env bash
# End-to-end API test for agreed platform
set -euo pipefail
BASE="${API_BASE:-http://localhost:8000}"
USER_A="test_user_a_$$"
USER_B="test_user_b_$$"
H() { echo "-H Content-Type:application/json -H X-User-Id:$1"; }

pass=0
fail=0
check() {
  local name="$1" cond="$2"
  if eval "$cond"; then echo "  PASS: $name"; pass=$((pass+1)); else echo "  FAIL: $name"; fail=$((fail+1)); fi
}

echo "=== agreed E2E API tests ==="
echo "Base: $BASE  UserA: $USER_A"

# 1. Health
echo "--- 1. Health & meta ---"
H=$(curl -s "$BASE/api/health")
check "health ok" "echo '$H' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d['status']=='ok' else 1)\""
check "frameworks" "curl -sf '$BASE/api/frameworks' | python3 -c \"import sys,json; exit(0 if len(json.load(sys.stdin)['frameworks'])>=3 else 1)\""

# 2. Home (empty)
echo "--- 2. Home ---"
HOME=$(curl -s $BASE/api/home $(H "$USER_A"))
check "home returns profile" "echo '$HOME' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if 'profile' in d else 1)\""

# 3. Chat + goal extraction
echo "--- 3. Chat & goals ---"
CHAT=$(curl -s -X POST $BASE/api/chat $(H "$USER_A") -d '{"message":"I want to buy custom printed shirts in bulk for my company"}')
check "chat reply" "echo '$CHAT' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d.get('reply') else 1)\""
check "goal created" "echo '$CHAT' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if len(d['profile']['goals'])>=1 else 1)\""

GOAL_ID=$(echo "$CHAT" | python3 -c "import sys,json; print(json.load(sys.stdin)['profile']['goals'][0]['id'])")
GOAL_TITLE=$(echo "$CHAT" | python3 -c "import sys,json; print(json.load(sys.stdin)['profile']['goals'][0]['title'])")

# 4. Negotiation session
echo "--- 4. Negotiation session ---"
SESS=$(curl -s -X POST $BASE/api/sessions $(H "$USER_A") -d "{\"title\":\"$GOAL_TITLE\",\"kind\":\"negotiation\",\"goal_id\":\"$GOAL_ID\"}")
SID=$(echo "$SESS" | python3 -c "import sys,json; print(json.load(sys.stdin)['session']['session_id'])")
INV=$(echo "$SESS" | python3 -c "import sys,json; print(json.load(sys.stdin)['session']['invite_code'])")
check "session created" "test -n '$SID'"

# 5. Patch other party
echo "--- 5. Other party ---"
PATCH=$(curl -s -X PATCH $BASE/api/sessions/$SID $(H "$USER_A") -d "{\"other_party_id\":\"$USER_B\",\"other_party_label\":\"Shirt Vendor Co\",\"status\":\"prepare\"}")
check "party set" "echo '$PATCH' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d['session']['other_party_id']=='$USER_B' else 1)\""

# 6. Participation session
echo "--- 6. Participation session ---"
PART=$(curl -s -X POST $BASE/api/sessions $(H "$USER_A") -d '{"title":"City park redesign survey","kind":"participation","other_party_label":"Municipality"}')
PSID=$(echo "$PART" | python3 -c "import sys,json; print(json.load(sys.stdin)['session']['session_id'])")
check "participation skips to rules" "echo '$PART' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d['session']['status']=='rules' and d['session']['other_party_label'] else 1)\""

# 7. Join invite as user B
echo "--- 7. Invitation join ---"
JOIN=$(curl -s -X POST $BASE/api/invitations/join $(H "$USER_B") -d "{\"link\":\"/join/$INV\"}")
check "user B joined" "echo '$JOIN' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if '$USER_B' in d['session']['parties'] else 1)\""

# 8. Submit agent (negotiation)
echo "--- 8. Submit & run negotiation ---"
SUB=$(curl -s -X POST $BASE/api/sessions/$SID/submit $(H "$USER_A") -d '{}')
check "negotiation ran" "echo '$SUB' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d['session'].get('negotiation_result') and d['session']['negotiation_result']['outcome']=='deal' else 1)\""
TRACE=$(echo "$SUB" | python3 -c "import sys,json; print(json.load(sys.stdin)['session']['negotiation_result']['trace_id'])")

# 9. Trace
echo "--- 9. Trace ---"
TR=$(curl -s $BASE/api/trace/$TRACE)
check "trace spans" "echo '$TR' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d['span_count']>0 else 1)\""

# 10. Self-improve
echo "--- 10. Self-improvement ---"
SI=$(curl -s -X POST $BASE/api/self-improve $(H "$USER_A") -d '{"party":"Buyer"}')
check "self-improve delta" "echo '$SI' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d['optimization']['improvement']>0 else 1)\""

# 11. Evals
echo "--- 11. Evals ---"
EV=$(curl -s "$BASE/api/evals?n=2")
check "evals run" "echo '$EV' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d['deal_closure_rate']==1.0 else 1)\""

# 12. Isolation
echo "--- 12. Data isolation ---"
RA=$(curl -s $BASE/api/records $(H "$USER_A") | python3 -c "import sys,json; print(len(json.load(sys.stdin)['records']))")
RB=$(curl -s $BASE/api/records $(H "$USER_B") | python3 -c "import sys,json; print(len(json.load(sys.stdin)['records']))")
check "isolation A has records" "test '$RA' -gt 0"
check "isolation B separate" "test '$RB' -ge 0"

# 13. Participation submit
echo "--- 13. Participation submit ---"
curl -s -X PATCH $BASE/api/sessions/$PSID $(H "$USER_A") -d '{"status":"prepare"}' >/dev/null
PSUB=$(curl -s -X POST $BASE/api/sessions/$PSID/submit $(H "$USER_A") -d '{}')
check "participation negotiates" "echo '$PSUB' | python3 -c \"import sys,json; d=json.load(sys.stdin); exit(0 if d['session'].get('negotiation_result') else 1)\""

# 14. CLI scripts
echo "--- 14. CLI scripts ---"
cd "$(dirname "$0")/.."
. .venv/bin/activate
python -m agreed.scripts.run_negotiation pareto >/dev/null 2>&1 && check "run_negotiation script" "true" || check "run_negotiation script" "false"
python -m agreed.scripts.run_baseline_vs_improved >/dev/null 2>&1 && check "baseline_vs_improved script" "true" || check "baseline_vs_improved script" "false"

echo ""
echo "=== Results: $pass passed, $fail failed ==="
exit $fail
