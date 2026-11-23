#!/usr/bin/env bash
# One command for a live demo: the Firebase Auth emulator, the backend, two
# demo accounts with finished reviews, and the app. Needs no Firebase project
# and no Groq key. Ctrl+C stops everything it started. Walkthrough: DEMO.md.
#
#   ./demo.sh            start (demo reviews are made once, then reused)
#   ./demo.sh --reset    redo every demo review from scratch
set -euo pipefail
set -m # each service in its own process group, so stopping it stops its children

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT=demo-whatlawsays
AUTH_PORT=9099
API_PORT=8010
APP_PORT=5173
APP="http://localhost:$APP_PORT"
RESET=""

for arg in "$@"; do
  case "$arg" in
    --reset) RESET="--reset" ;;
    -h | --help) sed -n '2,7p' "$0" | cut -c3-; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\ndemo: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed. $2"; }
listening() { lsof -iTCP:"$1" -sTCP:LISTEN -n -P >/dev/null 2>&1; }
env_value() { grep -E "^$1=" "$ROOT/backend/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'" || true; }

need uv "See https://docs.astral.sh/uv/getting-started/installation/"
need npm "Install Node.js 20 or newer."
need curl ""
need lsof ""

for port in $AUTH_PORT $API_PORT $APP_PORT; do
  if listening "$port"; then
    die "port $port is already in use. See what holds it with: lsof -iTCP:$port -sTCP:LISTEN"
  fi
done

LOGS="$(mktemp -d "${TMPDIR:-/tmp}/whatlawsays-demo.XXXXXX")"
pids=()
names=()

stop_all() {
  trap - EXIT INT TERM
  if [ ${#pids[@]} -gt 0 ]; then
    say "Stopping the demo"
    for pid in "${pids[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
  fi
}
trap stop_all EXIT
trap 'exit 130' INT TERM

# start NAME DIR COMMAND...: run in the background, logging to $LOGS/NAME.log
start() {
  local name=$1 dir=$2
  shift 2
  (cd "$dir" && exec "$@") >"$LOGS/$name.log" 2>&1 &
  pids+=($!)
  names+=("$name")
}

# wait_for URL SECONDS NAME
wait_for() {
  local deadline=$((SECONDS + $2))
  until curl -sf -o /dev/null "$1"; do
    [ "$SECONDS" -lt "$deadline" ] || die "$3 did not start within $2 s. Its log: $LOGS/$3.log"
    sleep 1
  done
}

# --- dependencies --------------------------------------------------------------
[ -d "$ROOT/frontend/node_modules" ] || { say "Installing frontend packages"; (cd "$ROOT/frontend" && npm ci); }
(cd "$ROOT/backend" && uv sync --quiet)

# --- the statute corpus (Qdrant) ---------------------------------------------
QDRANT_URL="${QDRANT_URL:-$(env_value QDRANT_URL)}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
if ! curl -sf -o /dev/null "$QDRANT_URL/collections"; then
  need docker "Qdrant is not running at $QDRANT_URL, and Docker is needed to start it."
  say "Starting Qdrant"
  docker compose -f "$ROOT/docker-compose.yml" up -d qdrant >/dev/null
  wait_for "$QDRANT_URL/collections" 60 qdrant
fi
points=$(curl -sf "$QDRANT_URL/collections/whatlawsays_legal_corpus" | grep -o '"points_count":[0-9]*' | cut -d: -f2 || true)
if [ "${points:-0}" -eq 0 ]; then
  say "Loading the statute corpus into Qdrant (first run only; takes a few minutes)"
  (cd "$ROOT/backend" && uv run python -m scripts.ingest_legal_corpus)
fi

db_port=$(env_value DATABASE_URL | sed -nE 's#.*@[^:/]+:([0-9]+)/.*#\1#p')
if ! listening "${db_port:-5433}"; then
  echo "Note: no Postgres on port ${db_port:-5433}. Reviews are kept in memory and made again on every start."
fi

# --- services ----------------------------------------------------------------
say "Starting the sign-in emulator, the backend and the app"
start emulator "$ROOT/frontend" ./node_modules/.bin/firebase emulators:start --only auth --project "$PROJECT"
wait_for "http://127.0.0.1:$AUTH_PORT/" 60 emulator

export FIREBASE_PROJECT_ID=$PROJECT FIREBASE_AUTH_EMULATOR_HOST="127.0.0.1:$AUTH_PORT"
start backend "$ROOT/backend" uv run uvicorn src.main:app --host 127.0.0.1 --port "$API_PORT"
# The first start downloads the embedding and reranker models.
wait_for "http://127.0.0.1:$API_PORT/health" 600 backend

BACKEND_URL="http://127.0.0.1:$API_PORT" start app "$ROOT/frontend" ./node_modules/.bin/vite --mode demo --port "$APP_PORT" --strictPort

say "Preparing the demo accounts"
(cd "$ROOT/backend" && uv run python -m scripts.seed_demo --api "http://127.0.0.1:$API_PORT" $RESET)
wait_for "$APP/" 60 app

# --- ready -------------------------------------------------------------------
say "WhatLawSays demo is running"
echo "  App            $APP"
(cd "$ROOT" && node -e '
  const spec = require("./frontend/src/auth/demo-accounts.json");
  for (const a of spec.accounts) {
    console.log(`  ${a.name.padEnd(14)} ${process.argv[1]}/demo/${a.id}   one click; ${a.reviews.length} reviews`);
  }
  console.log(`  Password       ${spec.password}   (for ${spec.accounts.map((a) => a.email).join(", ")})`);
' "$APP")
echo "  Walkthrough    DEMO.md"
if [ -z "${GROQ_API_KEY:-}" ] && [ -z "$(env_value GROQ_API_KEY)" ]; then
  echo
  echo "  No GROQ_API_KEY in backend/.env: contract red flags come from the built-in rules"
  echo "  (complete for the demo contracts); scenario analysis and Q&A are basic without it."
fi
echo
echo "  Logs in $LOGS"
echo "  Ctrl+C stops everything."

# Stay up until Ctrl+C, or until a service dies.
while true; do
  for i in "${!pids[@]}"; do
    if ! kill -0 "${pids[$i]}" 2>/dev/null; then
      die "${names[$i]} stopped unexpectedly. Its log: $LOGS/${names[$i]}.log"
    fi
  done
  sleep 2
done
