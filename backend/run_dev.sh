#!/usr/bin/env bash
# Start the agreed API with a reliable DB path and hot reload.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
export AGREED_DB_PATH="${AGREED_DB_PATH:-/tmp/agreed/agreed.db}"
mkdir -p "$(dirname "$AGREED_DB_PATH")"
source .venv/bin/activate

if lsof -i ":$PORT" -P -n >/dev/null 2>&1; then
  echo "Port $PORT is already in use."
  if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    echo "An agreed API is already running → http://localhost:$PORT"
    echo "Chat should work. To restart fresh: kill \$(lsof -t -i:$PORT) && ./run_dev.sh"
    exit 0
  fi
  echo "Killing stale process on port $PORT..."
  lsof -t -i:"$PORT" | xargs kill -9 2>/dev/null || true
  sleep 1
fi

echo "agreed API → http://localhost:$PORT  (db: $AGREED_DB_PATH)"
exec uvicorn agreed.api.server:app --reload --host 127.0.0.1 --port "$PORT"
