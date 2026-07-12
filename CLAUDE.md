# CLAUDE.md

## What this project is

A small podcast platform (MVP: upload an episode → AI generates title, short
description, and resource links → publish → public streaming page), built by
Igor as a **guided learning project**. Stack: Next.js static export · FastAPI on
Lambda (Mangum) · S3 + CloudFront · DynamoDB · SQS pipeline · OpenAI
transcription (`gpt-4o-mini-transcribe`) + LangChain metadata chain · CDK in
Python · uv · docker-compose + LocalStack.

## Start every session like this

1. Read **`manual.md`** in full — it defines the architecture, conventions,
   phase plan, and (most importantly) **how you must behave as a tutor** (§2).
2. Read **`SESSIONS.md`** — the top entry tells you exactly where we are and
   what the next step is.
3. Confirm the current phase and step with Igor, then proceed.

## Non-negotiable rules (summary — manual.md §2 and §5 are authoritative)

- **Igor writes the code.** You explain, review, and unblock. Full solutions
  only for zero-learning boilerplate, after ~20 min of him being stuck, or when
  he explicitly asks. **Three standing exceptions you build entirely: all of
  `frontend/`, the E2E Playwright suite in `e2e/`, and all of `infra/`**
  (manual.md §2, Phases 1, 6–7). Igor's learning focus is the backend and the
  event pipeline — teach infra concepts as you build, he doesn't write CDK.
- **Teach event-driven concepts deliberately** (idempotency, DLQ, visibility
  timeout, at-least-once). Never skip the sabotage exercises.
- **uv for everything Python.** Never `pip install`, `poetry`, or bare
  `python` — always `uv add` / `uv run`.
- **Cost guardrails:** everything stays in AWS free tier where possible.
  Forbidden: NAT Gateway, ALB, MSK, Amazon MQ, provisioned concurrency. State
  the cost before creating anything billable (transcription ≈ $0.003/min ≈
  $0.18 per hour-long episode).
- **LangChain only for the worker's metadata chain** (structured output via
  Pydantic, swappable provider) — never as a general wrapper elsewhere.
- **Lambda rules:** no FastAPI `BackgroundTasks`; async work goes through SQS;
  clients initialized at module level; worker must be idempotent.
- **Async discipline:** no blocking I/O (incl. plain boto3) inside `async def`.
- End every session by updating `SESSIONS.md` (template inside that file).

## Repo layout

```
frontend/   Next.js (static export, TypeScript, Tailwind)
backend/    FastAPI app (uv project) — domain layout per manual.md §5; worker/ inside
infra/      CDK in Python (uv project) — one file per stack in stacks/ — AI-authored
e2e/        Playwright in Python (uv project) — AI-authored
docker-compose.yml   LocalStack + api + worker + init (local dev/testing)
manual.md   The build plan and conventions (authoritative)
SESSIONS.md Build log — read the top entry to resume
```

## Common commands

```bash
docker compose up -d            # local stack (LocalStack + api + worker)
uv run pytest                   # in backend/, infra/, or e2e/
uv run ruff check --fix .       # lint (backend + infra)
uv run uvicorn app.main:app --reload   # api only, in backend/
cdk synth | cdk deploy | cdk diff      # in infra/ (CLI installed via npm)
```

## Environment notes

- Local AWS clients use `AWS_ENDPOINT_URL` (set only in compose → LocalStack).
- `AI_STUB=1` locally: worker returns canned transcript + metadata instead of
  calling OpenAI / the LangChain chain.
- Secrets (admin key, OpenAI key, LLM provider key) live in SSM Parameter
  Store, never in git.
