#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# entrypoint.sh — minimal service dispatcher for the candidate container.
#
# Usage:
#   entrypoint.sh app         -> wait for Postgres, then uvicorn
#   entrypoint.sh llm-proxy   -> start the LLM proxy on :8001
#   entrypoint.sh checkpoint  -> run scripts/checkpoint.sh (looped)
#   entrypoint.sh <anything>  -> exec the args verbatim
# ---------------------------------------------------------------------------
set -euo pipefail

CMD="${1:-app}"
shift || true

wait_for_postgres() {
  local host="${POSTGRES_HOST:-db}"
  local port="${POSTGRES_PORT:-5432}"
  local user="${POSTGRES_USER:-rag}"
  local db="${POSTGRES_DB:-rag}"
  local tries=60
  echo "[entrypoint] waiting for Postgres at ${host}:${port}..."
  while ! pg_isready -h "$host" -p "$port" -U "$user" -d "$db" >/dev/null 2>&1; do
    tries=$((tries - 1))
    if [ "$tries" -le 0 ]; then
      echo "[entrypoint] Postgres did not become ready in time" >&2
      exit 1
    fi
    sleep 1
  done
  echo "[entrypoint] Postgres ready."
}

case "$CMD" in
  app)
    wait_for_postgres
    exec uvicorn src.main:app --host 0.0.0.0 --port 8000 "$@"
    ;;
  llm-proxy)
    exec uvicorn scripts.llm_proxy.proxy:app --host 0.0.0.0 --port 8001 "$@"
    ;;
  checkpoint)
    exec bash /work/scripts/checkpoint.sh "$@"
    ;;
  bash|sh)
    exec "$CMD" "$@"
    ;;
  *)
    exec "$CMD" "$@"
    ;;
esac
