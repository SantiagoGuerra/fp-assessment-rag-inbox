#!/usr/bin/env python3
"""score_l1.py — aggregate L1 signals into final-l1.json.

Satisfies RF-201..207. Reads pre-generated reports when available
(semgrep-report.json, bandit-report.json, gitleaks-report.json,
coverage.json) and runs cheap checks inline (pytest summary, ruff, git
metrics). Total runtime budget <2 min (RF-205).

Exit codes:
    0  -> pass
    2  -> hard fail (secret, semgrep CRITICAL, <50% tests pass, <30% coverage)

The JSON schema is documented in the REQUIREMENTS doc; keep in sync.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Report readers — each returns a normalised dict. Missing files are non-fatal;
# we score 0 for that dimension and note it in the output.
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def run_tests() -> dict[str, Any]:
    """Run pytest in JSON-summary mode. Returns pass/fail/skip counts."""
    # We run a light, no-cov pass purely for counts — `make test` already
    # produced coverage.json.
    cmd = [
        sys.executable, "-m", "pytest", "tests/",
        "--tb=no", "-q", "--no-header",
    ]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=90, check=False
        )
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return {"passed": 0, "failed": 0, "skipped": 0, "errors": 1, "raw": "timeout"}

    # Parse the summary line e.g. "5 failed, 12 passed, 2 skipped in 3.1s"
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for token in ("passed", "failed", "skipped", "error", "errors"):
        # naive but resilient
        for line in reversed(out.strip().splitlines()):
            if token in line:
                try:
                    parts = line.replace(",", "").split()
                    for i, w in enumerate(parts):
                        if w.startswith(token) and i > 0 and parts[i - 1].isdigit():
                            key = "errors" if token.startswith("error") else token
                            counts[key] += int(parts[i - 1])
                            break
                    break
                except Exception:
                    pass
    counts["duration_s"] = round(time.time() - started, 2)
    return counts


def run_ruff() -> dict[str, int]:
    """ruff check in JSON mode — produces a list of diagnostics."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json"],
            cwd=ROOT, capture_output=True, text=True, timeout=60, check=False,
        )
        data = json.loads(proc.stdout or "[]")
    except Exception:
        return {"warn": 0, "err": 0, "total": 0}
    warn, err = 0, 0
    for item in data:
        # ruff categorises via rule code (E=err, W=warn in pycodestyle; F=err pyflakes).
        code = str(item.get("code", ""))
        if code.startswith(("E", "F", "B")):
            err += 1
        else:
            warn += 1
    return {"warn": warn, "err": err, "total": len(data)}


def read_semgrep() -> dict[str, int]:
    data = _read_json(ROOT / "semgrep-report.json") or {}
    buckets = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for finding in data.get("results", []):
        sev = str(finding.get("extra", {}).get("severity", "INFO")).upper()
        if sev in ("ERROR", "CRITICAL"):
            buckets["critical"] += 1
        elif sev == "HIGH":
            buckets["high"] += 1
        elif sev in ("WARNING", "MEDIUM"):
            buckets["medium"] += 1
        elif sev == "LOW":
            buckets["low"] += 1
        else:
            buckets["info"] += 1
    return buckets


def read_bandit() -> dict[str, int]:
    data = _read_json(ROOT / "bandit-report.json") or {}
    buckets = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for result in data.get("results", []):
        sev = str(result.get("issue_severity", "LOW")).upper()
        key = sev.lower() if sev.lower() in buckets else "low"
        buckets[key] += 1
    return buckets


def merge_sast(*bkts: dict[str, int]) -> dict[str, int]:
    out = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for b in bkts:
        for k in out:
            out[k] += int(b.get(k, 0))
    return out


def read_gitleaks() -> dict[str, Any]:
    data = _read_json(ROOT / "gitleaks-report.json")
    if data is None:
        return {"count": 0, "findings": []}
    if isinstance(data, list):
        return {"count": len(data), "findings": data}
    return {"count": 0, "findings": []}


def read_coverage() -> dict[str, float]:
    data = _read_json(ROOT / "coverage.json") or {}
    totals = data.get("totals", {})
    overall = float(totals.get("percent_covered", 0.0))
    # Modified-file coverage: candidate-session assumption — modified = any
    # file under src/ changed since session start. Use `git diff --name-only`
    # against the initial commit; fall back to "overall" if no git info.
    modified = _modified_coverage_pct(data)
    return {"pct_total": round(overall, 2), "pct_modified_files": round(modified, 2)}


def _modified_coverage_pct(coverage_data: dict) -> float:
    try:
        base = subprocess.run(
            ["git", "rev-list", "--max-parents=0", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip().splitlines()[0]
        names = subprocess.run(
            ["git", "diff", "--name-only", base, "HEAD", "--", "src/"],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip().splitlines()
    except Exception:
        return float(coverage_data.get("totals", {}).get("percent_covered", 0.0))
    if not names:
        return float(coverage_data.get("totals", {}).get("percent_covered", 0.0))
    files = coverage_data.get("files", {})
    covered, total = 0, 0
    for name in names:
        info = files.get(name) or files.get(str(Path(name)))
        if not info:
            continue
        summary = info.get("summary", {})
        covered += int(summary.get("covered_lines", 0))
        total += int(summary.get("num_statements", 0))
    if total == 0:
        return 0.0
    return 100.0 * covered / total


def git_metrics() -> dict[str, Any]:
    try:
        # Use the initial commit as the session anchor.
        base = subprocess.run(
            ["git", "rev-list", "--max-parents=0", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip().splitlines()[0]
    except Exception:
        return {
            "total_commits": 0, "avg_commit_size": 0, "large_commits": 0,
            "revert_count": 0, "weak_message_count": 0,
        }

    log = subprocess.run(
        ["git", "log", "--pretty=format:%H%x1f%s", "--numstat", f"{base}..HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=5,
    ).stdout

    commits: list[dict] = []
    current: dict | None = None
    for line in log.splitlines():
        if "\x1f" in line:
            if current:
                commits.append(current)
            sha, _, subj = line.partition("\x1f")
            current = {"sha": sha, "subject": subj, "lines": 0}
        elif line.strip() and current is not None:
            parts = line.split("\t")
            if len(parts) >= 2:
                try:
                    add = int(parts[0]) if parts[0] != "-" else 0
                    rm = int(parts[1]) if parts[1] != "-" else 0
                    current["lines"] += add + rm
                except ValueError:
                    pass
    if current:
        commits.append(current)

    total = len(commits)
    avg = (sum(c["lines"] for c in commits) / total) if total else 0
    large = sum(1 for c in commits if c["lines"] > 200)
    reverts = sum(1 for c in commits if c["subject"].lower().startswith("revert"))
    weak = sum(1 for c in commits if _is_weak_message(c["subject"]))

    return {
        "total_commits": total,
        "avg_commit_size": round(avg, 1),
        "large_commits": large,
        "revert_count": reverts,
        "weak_message_count": weak,
    }


def _is_weak_message(subject: str) -> bool:
    s = subject.strip().lower()
    if len(s) < 8:
        return True
    weak_tokens = {"wip", "fix", "update", "changes", "tmp", "test", "stuff", "misc"}
    return s in weak_tokens or s.split()[0] in weak_tokens and len(s.split()) == 1


# ---------------------------------------------------------------------------
# Rubric scoring — 0-5 per dimension (RF-202).
# Weights and exact thresholds live in .tech-lead-internal/RUBRIC_WEIGHTS.md.
# This script implements the mechanical mapping; evaluators adjust via L2/L3.
# ---------------------------------------------------------------------------

def score_correctness(tests: dict) -> int:
    total = tests["passed"] + tests["failed"] + tests.get("errors", 0)
    if total == 0:
        return 0
    ratio = tests["passed"] / total
    if ratio >= 0.95:
        return 5
    if ratio >= 0.85:
        return 4
    if ratio >= 0.70:
        return 3
    if ratio >= 0.50:
        return 2
    if ratio > 0:
        return 1
    return 0


def score_security(sast: dict, secrets_count: int) -> int:
    if secrets_count > 0 or sast["critical"] > 0:
        return 0
    if sast["high"] > 0:
        return 2
    if sast["medium"] > 2:
        return 3
    if sast["medium"] > 0:
        return 4
    return 5


def score_code_quality(lint: dict, coverage_pct: float) -> int:
    score = 5
    if lint["err"] > 0:
        score -= 2
    if lint["warn"] > 10:
        score -= 1
    if coverage_pct < 70:
        score -= 1
    if coverage_pct < 50:
        score -= 1
    return max(score, 0)


def score_performance(tests: dict) -> int:
    # Real perf is measured at L2 (load test). L1 only notes whether the
    # suite completed in a reasonable time; 5 if <60s, 3 if <120s, else 1.
    dur = float(tests.get("duration_s", 0))
    if dur == 0:
        return 3
    if dur < 60:
        return 5
    if dur < 120:
        return 3
    return 1


def score_git_hygiene(git: dict) -> int:
    if git["total_commits"] == 0:
        return 0
    score = 5
    if git["large_commits"] > 2:
        score -= 2
    if git["weak_message_count"] > git["total_commits"] // 2:
        score -= 2
    if git["revert_count"] > 2:
        score -= 1
    if git["avg_commit_size"] > 300:
        score -= 1
    return max(score, 1)


def score_ai_usage_signal(git: dict) -> int:
    # Crude L1 proxy: lots of enormous commits + weak messages = likely
    # blind-AI dump. Evaluators refine at L2/L3 using prompt logs.
    blind = (
        git["large_commits"] >= 3 and
        git["weak_message_count"] >= git["total_commits"] // 2 and
        git["total_commits"] > 0
    )
    return 2 if blind else 4


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

@dataclass
class Report:
    generated_at: str
    scores_by_dimension: dict[str, int] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)
    git_metrics: dict[str, Any] = field(default_factory=dict)
    hard_fail: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)
    exit_code: int = 0
    runtime_seconds: float = 0.0


def assemble(out_path: Path) -> int:
    t0 = time.time()

    tests = run_tests()
    lint = run_ruff()
    sast = merge_sast(read_semgrep(), read_bandit())
    secrets = read_gitleaks()
    cov = read_coverage()
    git = git_metrics()

    scores = {
        "correctness": score_correctness(tests),
        "security": score_security(sast, secrets["count"]),
        "code_quality": score_code_quality(lint, cov["pct_modified_files"]),
        "performance": score_performance(tests),
        "git_hygiene": score_git_hygiene(git),
        "ai_usage_signal": score_ai_usage_signal(git),
    }

    # Hard-fail rules (RF-207)
    reasons: list[str] = []
    tests_total = tests["passed"] + tests["failed"] + tests.get("errors", 0)
    pass_pct = (100.0 * tests["passed"] / tests_total) if tests_total else 0.0
    if secrets["count"] > 0:
        reasons.append(f"gitleaks detected {secrets['count']} secret(s)")
    if sast["critical"] > 0:
        reasons.append(f"semgrep reported {sast['critical']} CRITICAL finding(s)")
    if tests_total > 0 and pass_pct < 50.0:
        reasons.append(f"tests pass rate {pass_pct:.1f}% < 50%")
    if cov["pct_modified_files"] < 30.0:
        reasons.append(f"coverage on modified files {cov['pct_modified_files']:.1f}% < 30%")

    rpt = Report(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        scores_by_dimension=scores,
        counts={
            "tests": {
                "pass": tests["passed"],
                "fail": tests["failed"],
                "skip": tests["skipped"],
                "error": tests.get("errors", 0),
                "duration_s": tests.get("duration_s", 0),
            },
            "lint": {"warn": lint["warn"], "err": lint["err"]},
            "sast": sast,
            "secrets": {"count": secrets["count"]},
            "coverage": cov,
        },
        git_metrics=git,
        hard_fail=bool(reasons),
        hard_fail_reasons=reasons,
        exit_code=2 if reasons else 0,
        runtime_seconds=round(time.time() - t0, 2),
    )

    out_path.write_text(json.dumps(asdict(rpt), indent=2), encoding="utf-8")
    print(json.dumps(asdict(rpt), indent=2))
    return rpt.exit_code


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", "-o", default="final-l1.json", type=Path)
    args = ap.parse_args()
    return assemble(args.output)


if __name__ == "__main__":
    sys.exit(main())
