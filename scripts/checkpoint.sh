#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# checkpoint.sh — snapshot the candidate's workspace every 20 min (RF-301..307).
#
# Behaviour:
#   - One-shot when CHECKPOINT_LOOP is unset (used by `make checkpoint`).
#   - Loops every CHECKPOINT_INTERVAL_SECONDS (default 1200) when
#     CHECKPOINT_LOOP=1 — the compose `checkpoint` service uses this.
#
# Artefacts per checkpoint (RF-302):
#   /artifacts/checkpoint-<iso>/
#     ├─ diff.patch        (git diff vs last checkpoint / initial commit)
#     ├─ commits.log       (git log --oneline --numstat since session start)
#     ├─ tests.txt         (best-effort `make test` output, non-fatal)
#     └─ prompts.json      (merge of .claude/sessions/*.json + Cline workspace)
#
# UID / perms:
#   Designed to run as UID 2000 (`checkpoint`) — docker-compose enforces this.
#   Files are chmod 0444 (read-only for everyone) so the candidate can inspect
#   but not modify (RF-303, RNF-06). Bash portable for macOS + Linux.
# ---------------------------------------------------------------------------
set -u
set -o pipefail

WORKDIR="${WORKDIR:-/work}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-/artifacts}"
INTERVAL="${CHECKPOINT_INTERVAL_SECONDS:-1200}"
SESSION_START_FILE="${ARTIFACTS_DIR}/.session-start"
LAST_CHECKPOINT_FILE="${ARTIFACTS_DIR}/.last-checkpoint"

log() { printf '[checkpoint %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }

iso_now() { date -u +%Y-%m-%dT%H-%M-%SZ; }

ensure_session_start() {
  mkdir -p "$ARTIFACTS_DIR" 2>/dev/null || true
  if [ ! -f "$SESSION_START_FILE" ]; then
    iso_now > "$SESSION_START_FILE" 2>/dev/null || true
  fi
}

run_once() {
  ensure_session_start

  local ts out
  ts="$(iso_now)"
  out="${ARTIFACTS_DIR}/checkpoint-${ts}"

  log "writing ${out}"
  mkdir -p "$out" || { log "cannot mkdir $out"; return 1; }

  # ---- diff.patch -------------------------------------------------------
  if [ -d "${WORKDIR}/.git" ]; then
    # Prefer diff against last checkpoint HEAD; fall back to initial commit.
    local base=""
    if [ -f "$LAST_CHECKPOINT_FILE" ]; then
      base="$(cat "$LAST_CHECKPOINT_FILE" 2>/dev/null || true)"
    fi
    if [ -z "$base" ] || ! git -C "$WORKDIR" cat-file -e "$base" 2>/dev/null; then
      base="$(git -C "$WORKDIR" rev-list --max-parents=0 HEAD 2>/dev/null | head -n1 || true)"
    fi
    if [ -n "$base" ]; then
      git -C "$WORKDIR" diff "$base" -- > "${out}/diff.patch" 2>/dev/null || true
    else
      # No commits yet — capture working-tree state as a single "add all" patch.
      git -C "$WORKDIR" diff --no-index /dev/null "$WORKDIR" > "${out}/diff.patch" 2>/dev/null || true
    fi
    # Remember current HEAD (best-effort).
    git -C "$WORKDIR" rev-parse HEAD > "$LAST_CHECKPOINT_FILE" 2>/dev/null || true
  else
    log "no .git — skipping diff"
    : > "${out}/diff.patch"
  fi

  # ---- commits.log ------------------------------------------------------
  if [ -d "${WORKDIR}/.git" ]; then
    git -C "$WORKDIR" log --oneline --numstat --no-color \
      > "${out}/commits.log" 2>/dev/null || : > "${out}/commits.log"
  else
    : > "${out}/commits.log"
  fi

  # ---- tests.txt (best-effort) -----------------------------------------
  # Run as candidate would — but `make test` needs the venv + DB which may
  # not be reachable from this UID. We capture whatever we can, never fail.
  (
    cd "$WORKDIR" || exit 0
    timeout 120 make test 2>&1 || true
  ) > "${out}/tests.txt" 2>&1 || true

  # ---- prompts.json (Claude Code + Cline) ------------------------------
  python3 - "$WORKDIR" "${out}/prompts.json" <<'PY' 2>/dev/null || echo "{}" > "${out}/prompts.json"
import json, os, sys, glob, pathlib

workdir, outpath = sys.argv[1], sys.argv[2]
payload = {"claude_code": [], "cline": []}

# Claude Code sessions (RF-306)
for p in sorted(glob.glob(os.path.join(workdir, ".claude", "sessions", "*.json"))):
    try:
        with open(p, "r", encoding="utf-8") as f:
            payload["claude_code"].append({"file": os.path.relpath(p, workdir), "content": json.load(f)})
    except Exception as e:
        payload["claude_code"].append({"file": p, "error": str(e)})

# Cline workspace prompts (RF-307) — heuristic; location varies by VS Code setup.
cline_candidates = [
    os.path.join(workdir, ".vscode", "cline"),
    os.path.join(workdir, ".cline"),
    os.path.expanduser("~/.vscode-server/data/User/globalStorage/saoudrizwan.claude-dev"),
]
for root in cline_candidates:
    if not os.path.isdir(root):
        continue
    for p in pathlib.Path(root).rglob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                payload["cline"].append({"file": str(p), "content": json.load(f)})
        except Exception as e:
            payload["cline"].append({"file": str(p), "error": str(e)})

with open(outpath, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, default=str)
PY

  # ---- lock down perms -------------------------------------------------
  chmod -R a-w "$out" 2>/dev/null || true
  find "$out" -type f -exec chmod 0444 {} \; 2>/dev/null || true
  chmod 0555 "$out" 2>/dev/null || true

  log "checkpoint complete: ${out}"
}

main() {
  ensure_session_start
  if [ "${CHECKPOINT_LOOP:-0}" = "1" ]; then
    log "loop mode — interval ${INTERVAL}s"
    # Take one on startup so RNF-15 (≤19 min loss) holds even on early crash.
    run_once || true
    while true; do
      sleep "$INTERVAL"
      run_once || true
    done
  else
    run_once
  fi
}

main "$@"
