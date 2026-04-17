"""LLM proxy — Anthropic Messages API v1 compatible (RF-401..406, RNF-05).

- Candidate-facing server on port 8001.
- Accepts any `x-api-key` that starts with the fake key
  (`FP_PROXY_FAKE_KEY`, default `fp-proxy-key-local`).
- Forwards upstream to https://api.anthropic.com using the REAL key from
  `ANTHROPIC_API_KEY_REAL` — that env var is ONLY set on this service,
  never on the candidate container (see docker-compose.yml).
- Tracks approximate USD spend via token * per-1M-token prices and rejects
  with HTTP 402 when the budget is exhausted (RF-405).
- Logs every request/response to `/artifacts/llm-trace/<session>.jsonl`
  with `{ts, model, prompt, response, tokens_in, tokens_out, cost_usd,
  cumulative_usd}`. Real key is NEVER logged.
- State (cumulative spend) persists to `/artifacts/llm-budget.json` so it
  survives proxy restarts within a session.

We implement a minimal forward with httpx directly rather than pulling in
litellm — it's one endpoint, simpler to audit, and avoids the extra dep.
A config.yaml ships alongside for operators to override pricing / budget
without editing code.
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Harden file creation: trace + budget files must not be world-readable
# (RNF-06 — checkpoint/proxy data stays confined to the checkpoint UID).
os.umask(0o077)

# Request hardening caps.
MAX_BODY_BYTES = 256 * 1024  # 256 KB — refuse anything larger.
RATE_LIMIT_PER_MIN = 60  # per-key requests per rolling 60s window.

# ---------------------------------------------------------------------------
# Configuration — env overrides YAML overrides defaults.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.yaml"


def _load_config() -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            cfg = {}
    cfg.setdefault("upstream_url", os.environ.get("FP_PROXY_UPSTREAM", "https://api.anthropic.com"))
    cfg.setdefault("budget_usd", float(os.environ.get("FP_PROXY_BUDGET_USD", "2.0")))
    cfg.setdefault("fake_key_prefix", os.environ.get("FP_PROXY_FAKE_KEY", "fp-proxy-key-local"))
    cfg.setdefault("state_file", os.environ.get("FP_PROXY_STATE_FILE", "/artifacts/llm-budget.json"))
    cfg.setdefault("trace_dir", os.environ.get("FP_PROXY_TRACE_DIR", "/artifacts/llm-trace"))
    cfg.setdefault("session_id", os.environ.get("FP_PROXY_SESSION_ID", "default"))
    cfg.setdefault("pricing", {
        # USD per 1M tokens — ballpark; override via config.yaml.
        "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-5-haiku":  {"input": 0.80, "output": 4.00},
        "claude-3-opus":     {"input": 15.00, "output": 75.00},
        "default":           {"input": 3.00, "output": 15.00},
    })
    return cfg


CFG = _load_config()
REAL_KEY = os.environ.get("ANTHROPIC_API_KEY_REAL", "").strip()

app = FastAPI(title="fp-llm-proxy", version="1.0.0")

_state_lock = Lock()


# ---------------------------------------------------------------------------
# Budget state (persisted JSON).
# ---------------------------------------------------------------------------

def _read_state() -> dict[str, float]:
    p = Path(CFG["state_file"])
    if not p.exists():
        return {"cumulative_usd": 0.0}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"cumulative_usd": 0.0}


def _write_state(state: dict[str, float]) -> None:
    p = Path(CFG["state_file"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(p)


def _price_for(model: str) -> dict[str, float]:
    pricing = CFG["pricing"]
    for prefix, rates in pricing.items():
        if prefix != "default" and model.startswith(prefix):
            return rates
    return pricing["default"]


def _cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    p = _price_for(model)
    return (tokens_in / 1_000_000.0) * p["input"] + (tokens_out / 1_000_000.0) * p["output"]


def _trace(entry: dict[str, Any]) -> None:
    d = Path(CFG["trace_dir"])
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{CFG['session_id']}.jsonl"
    # Defensive: never write the real key even if it leaked into entry.
    entry.pop("real_api_key", None)
    with f.open("a", encoding="utf-8") as h:
        h.write(json.dumps(entry, default=str) + "\n")


def _validate_candidate_key(headers) -> str:
    key = headers.get("x-api-key", "")
    if not key.startswith(CFG["fake_key_prefix"]):
        raise HTTPException(status_code=401, detail="invalid api key")
    return key


# Simple in-memory per-key rolling-window rate limiter.
_rate_buckets: dict[str, deque[float]] = {}
_rate_lock = Lock()


def _check_rate(key: str) -> None:
    now = time.monotonic()
    window = 60.0
    with _rate_lock:
        bucket = _rate_buckets.setdefault(key, deque())
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_PER_MIN:
            raise HTTPException(
                status_code=429,
                detail=f"rate limit: {RATE_LIMIT_PER_MIN} req/min per key",
            )
        bucket.append(now)


def _check_budget() -> float:
    state = _read_state()
    spent = float(state.get("cumulative_usd", 0.0))
    if spent >= float(CFG["budget_usd"]):
        raise HTTPException(
            status_code=402,
            detail=(
                f"LLM budget exhausted: spent ~${spent:.3f} of "
                f"${CFG['budget_usd']:.2f} limit. "
                "No further calls will be served for this session."
            ),
        )
    return spent


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    state = _read_state()
    return {
        "status": "ok",
        "session_id": CFG["session_id"],
        "cumulative_usd": state.get("cumulative_usd", 0.0),
        "budget_usd": CFG["budget_usd"],
        "has_real_key": bool(REAL_KEY),
    }


@app.post("/v1/messages")
async def messages(request: Request) -> JSONResponse:
    """Anthropic Messages API v1 compatible endpoint."""
    key = _validate_candidate_key(request.headers)
    _check_rate(key)
    if not REAL_KEY:
        raise HTTPException(status_code=503, detail="proxy not configured: missing ANTHROPIC_API_KEY_REAL")

    # Reject oversized bodies before reading them fully.
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=f"body > {MAX_BODY_BYTES} bytes")

    with _state_lock:
        _check_budget()

    body_bytes = await request.body()
    if len(body_bytes) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=f"body > {MAX_BODY_BYTES} bytes")
    try:
        payload = json.loads(body_bytes or b"{}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"invalid json: {e}") from e

    model = str(payload.get("model", "claude-3-5-sonnet-latest"))

    upstream_headers = {
        "x-api-key": REAL_KEY,
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
        "content-type": "application/json",
    }

    url = CFG["upstream_url"].rstrip("/") + "/v1/messages"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=upstream_headers, content=body_bytes)

    try:
        resp_json = resp.json()
    except Exception:
        resp_json = {"raw": resp.text}

    usage = resp_json.get("usage", {}) if isinstance(resp_json, dict) else {}
    tokens_in = int(usage.get("input_tokens", 0) or 0)
    tokens_out = int(usage.get("output_tokens", 0) or 0)
    cost = _cost_usd(model, tokens_in, tokens_out)

    with _state_lock:
        state = _read_state()
        state["cumulative_usd"] = float(state.get("cumulative_usd", 0.0)) + cost
        _write_state(state)
        cumulative = state["cumulative_usd"]

    _trace({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
        "prompt": payload,
        "response": resp_json,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
        "cumulative_usd": round(cumulative, 6),
        "upstream_status": resp.status_code,
    })

    return JSONResponse(content=resp_json, status_code=resp.status_code)


@app.post("/v1/messages/count_tokens")
async def count_tokens(request: Request) -> JSONResponse:
    """Pass-through for token counting — does not affect budget."""
    key = _validate_candidate_key(request.headers)
    _check_rate(key)
    if not REAL_KEY:
        raise HTTPException(status_code=503, detail="proxy not configured")
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=f"body > {MAX_BODY_BYTES} bytes")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=f"body > {MAX_BODY_BYTES} bytes")
    headers = {
        "x-api-key": REAL_KEY,
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
        "content-type": "application/json",
    }
    url = CFG["upstream_url"].rstrip("/") + "/v1/messages/count_tokens"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, content=body)
    return JSONResponse(content=resp.json() if resp.content else {}, status_code=resp.status_code)
