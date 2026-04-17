#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ci_local.sh — `make ci-local` wrapper. Runs lint, tests, SAST, secrets,
# and L1 scoring in sequence and prints a tidy summary. Each stage is
# non-fatal for the overall pipeline — score_l1 is the arbiter (RF-207).
# ---------------------------------------------------------------------------
set -u
set -o pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${here}/.." || exit 1

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; RESET=$'\033[0m'

declare -A STATUS=()
STAGES=(lint test sast secrets score-l1)

run_stage() {
  local name="$1"; shift
  local log="/tmp/ci-local-${name}.log"
  echo "${BOLD}== ${name} ==${RESET}"
  if make "$name" > >(tee "$log") 2>&1; then
    STATUS[$name]="${GREEN}PASS${RESET}"
  else
    STATUS[$name]="${RED}FAIL${RESET}"
  fi
  echo ""
}

for stage in "${STAGES[@]}"; do
  run_stage "$stage"
done

echo "${BOLD}=========================================="
echo " CI-LOCAL SUMMARY"
echo "==========================================${RESET}"
for stage in "${STAGES[@]}"; do
  printf "  %-12s %b\n" "$stage" "${STATUS[$stage]}"
done

if [ -f final-l1.json ]; then
  echo ""
  echo "${BOLD}-- final-l1.json (excerpt) --${RESET}"
  python3 - <<'PY' || true
import json, sys
try:
    with open("final-l1.json") as f:
        d = json.load(f)
    print(json.dumps({
        "hard_fail": d.get("hard_fail"),
        "scores_by_dimension": d.get("scores_by_dimension"),
        "counts": d.get("counts"),
        "exit_code": d.get("exit_code"),
    }, indent=2))
except Exception as e:
    print(f"(could not parse final-l1.json: {e})", file=sys.stderr)
PY
fi

# Exit non-zero only if L1 scoring itself reports hard fail.
if [ -f final-l1.json ]; then
  python3 -c 'import json,sys;sys.exit(json.load(open("final-l1.json")).get("exit_code",0))'
  exit $?
fi
exit 0
