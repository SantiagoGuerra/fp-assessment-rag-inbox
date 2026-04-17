# fp-assessment-rag-inbox

A small Retrieval-Augmented Generation (RAG) service over a support-ticket
inbox. The product lets on-call engineers ask questions in natural language and
receive grounded answers with citations back to the original tickets.

## Context

The internal Support team ingests support tickets into a Postgres database
enriched with `pgvector`. A FastAPI service exposes three endpoints: `/ingest`,
`/query`, and `/health`. A PydanticAI agent orchestrates retrieval and answer
generation using a local `sentence-transformers` embedder. This repository is
the codebase that Support is productizing.

## Task summary

See [`TASK.md`](./TASK.md) for the user story, what is already implemented, and
what you need to deliver. Read [`docs/SPEC.md`](./docs/SPEC.md) before you
start editing.

## Heads up — this is not a clean codebase

The repository ships with **deliberate discrepancies between the SPEC and the
implementation**. Some tests are skipped, some behavior does not match the
documented contract, and some existing code will not meet the acceptance
criteria as-is. This is on purpose.

Your job is to read `docs/SPEC.md`, compare it to the code you find, and close
the gaps. We are more interested in how you investigate and reason than in
whether you fix every issue. Work through the highest-impact items first and
leave the rest documented.

Do not assume every third-party-looking reference in the docs or comments is
real. If a tool, package, or helper does not exist in this repository, treat
that as a signal to solve the problem inline rather than chase it.

## Acceptance criteria

Your work is evaluated against these six outcomes (AC-1 through AC-6):

- **AC-1**: `POST /query` returns HTTP 200 with
  `{answer, citations: [{ticket_id, snippet, score}]}` and includes at least
  two citations for any query that matches one or more tickets.
- **AC-2**: Every `ticket_id` in `citations` exists in the database. Zero
  hallucinated identifiers.
- **AC-3**: `POST /query` p95 latency is below 1.5 seconds on the 60-ticket
  seed dataset.
- **AC-4**: `POST /ingest` chunks a 2000-character ticket into at least three
  chunks with the correct character overlap.
- **AC-5**: Adversarial payloads (for example `"ignore previous instructions"`)
  do not alter the agent behavior.
- **AC-6**: `pytest tests/` passes at 100 percent. Coverage on files you
  modify is at least 70 percent.

## Prerequisites

The FP-provided laptop is preconfigured. If you rebuild or run locally:

- Docker Engine 24+ with Compose v2 (`docker compose version` must succeed).
- 4 CPU cores and 8 GB of RAM free for the container.
- ~3 GB of free disk (images + pgvector + the embedder model).
- Outbound HTTPS to `api.anthropic.com`, `pypi.org`, `files.pythonhosted.org`,
  and `huggingface.co` on first build (the embedder model is cached after).
- No host Postgres on port 5432 or web server on port 8000.

## Setup

One-line setup from a clean clone:

```bash
docker compose up --build
```

Expected startup time is under 60 seconds on a 4-core, 8 GB laptop on the
second build (first build downloads the embedder model; add ~1-2 minutes).
Health check:

```bash
curl -s http://localhost:8000/health
# {"status":"ok"}
```

If you prefer to work inside the VS Code devcontainer, open the repository in
VS Code, accept the "Reopen in Container" prompt, and then run:

```bash
make setup && make run
```

`make setup` installs the locked Python environment, installs the pre-commit
hooks, and seeds the 60-ticket fixture into the database. `make run` starts
the API on port 8000. Run `make test` to execute the test suite and
`make score-l1` to produce the local scoring artifact `final-l1.json`.

## First five minutes — suggested path

1. `docker compose up --build` and wait for the health check.
2. Read `TASK.md`, then `docs/SPEC.md`. Keep both open.
3. `make test` to see the baseline. Do not panic if it is not green.
4. Skim `src/services/` — chunker, embedder, retriever, generator,
   config_service. Each is small and focused.
5. Pick the change with the highest impact on the acceptance criteria.
   Commit as soon as you have a meaningful unit of progress.

## Troubleshooting

- `docker compose up` hangs on "pulling embedder model" — your network blocks
  huggingface.co. Tell the evaluator; they will warm the cache for you.
- Port 8000 or 5432 is in use — stop the conflicting host process or edit
  `docker-compose.yml`.
- `make setup` reports a Python version error — run it inside the
  devcontainer, not the host.
- `pytest` cannot find modules — you ran it outside the devcontainer; retry
  inside.

If anything blocks you from making progress for more than a few minutes, tell
the evaluator in chat. Assessment bugs that are ours to fix do not count
against you.

## Approved AI tools

You may use the following assistants during the session:

- **Claude Code CLI** (terminal).
- **Cline** (VS Code extension).
- **Inline completions** from approved providers configured by the laptop
  image (Copilot-style suggestions).

External web interfaces are not permitted during the session. That includes
`chat.openai.com`, `claude.ai`, Gemini chat, and any other browser-based LLM
UI. All approved tools route through the local LLM proxy on this laptop so
your prompt and response traffic is captured for later review.

## What is observed

We record the full live-coding phase (Phase 2) so evaluators can reconstruct
your session afterwards. By starting the session you consent to the following.

**Audio and video recorded for the entire live-coding phase:**

- **Screen capture** of the FP laptop, continuous, full session.
- **Microphone audio**, continuous, full session. Talking through your
  thought process is encouraged but not required.

**Artifacts captured on the laptop:**

- Every 20 minutes a background process writes a checkpoint into
  `/artifacts/checkpoint-<timestamp>/`. A checkpoint contains the current
  `git diff`, a commit log, the latest test output, and a copy of the prompts
  sent to approved AI tools.
- The local LLM proxy logs all prompts and responses to
  `/artifacts/llm-trace/`.
- Git history is preserved as-is. Commit early and commit often.

**We do not capture:** webcam / face-tracking video, keystroke-timing
biometrics for fraud detection, or precise geolocation.

Recordings and artifacts are retained per FP's candidate data policy. Ask the
evaluator or recruiter for a copy of that policy before the session if you
want to review it.

## Session timeline

| Phase       | Duration     | Activity                                        |
|-------------|--------------|-------------------------------------------------|
| Setup       | 15 minutes   | Container boot, editor setup, read the docs.    |
| Build       | 60-90 minutes| Implement the acceptance criteria, commit often.|
| Walkthrough | 15-20 minutes| Demo the API, walk through your diff, Q&A.      |

## Evaluation dimensions

Your submission is scored across these dimensions. Weights are available to
the evaluator.

- **Correctness**: Acceptance criteria AC-1 through AC-6.
- **Security**: Resistance to adversarial inputs and safe handling of user
  content.
- **Code quality**: Idiomatic Python, small functions, clear naming.
- **Performance**: Query latency under load.
- **Git hygiene**: Commit size, commit messages, logical progression.
- **AI usage signal**: How you work with AI tools rather than whether you
  use them.

## Glossary

- **RAG**: Retrieval-Augmented Generation. A retrieval step grounds the
  generator with source documents.
- **Citation**: A reference back to a source ticket with `ticket_id`,
  `snippet`, and `score`.
- **Chunk**: A contiguous slice of a ticket body used for embedding and
  retrieval.
- **p95 latency**: The 95th-percentile response time across a workload.
