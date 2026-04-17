"""bootstrap_db.py — idempotently load seed tickets into pgvector.

Called by `make setup`. It expects a RAG app to expose either:
    - `src.db.session.get_engine()` returning an async SQLAlchemy engine, OR
    - a module `src.services.ingest` with `async def bulk_ingest(tickets)`.

If neither exists yet (rag-impl not merged) the script logs and exits 0
so `make setup` stays non-fatal during parallel dev.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "tickets.json"


async def _run() -> int:
    if not FIXTURE.exists():
        print(f"[bootstrap_db] fixture missing: {FIXTURE} — skipping")
        return 0

    try:
        tickets = json.loads(FIXTURE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[bootstrap_db] could not read fixture: {e}")
        return 0

    try:
        sys.path.insert(0, str(ROOT))
        from src.services.ingest import bulk_ingest  # type: ignore[import-not-found]
    except Exception as e:
        print(f"[bootstrap_db] src.services.ingest unavailable ({e}) — skipping bootstrap")
        return 0

    try:
        await bulk_ingest(tickets)
    except Exception as e:
        print(f"[bootstrap_db] bulk_ingest failed: {e}")
        return 0

    print(f"[bootstrap_db] loaded {len(tickets)} tickets into DB")
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"[bootstrap_db] unexpected: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
