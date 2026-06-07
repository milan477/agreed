#!/usr/bin/env bash
# Start the agreed API with a reliable DB path and hot reload.
set -euo pipefail
cd "$(dirname "$0")"
export AGREED_DB_PATH="${AGREED_DB_PATH:-/tmp/agreed/agreed.db}"
mkdir -p "$(dirname "$AGREED_DB_PATH")"
source .venv/bin/activate
echo "agreed API → http://localhost:8000  (db: $AGREED_DB_PATH)"
exec uvicorn agreed.api.server:app --reload --host 127.0.0.1 --port 8000
