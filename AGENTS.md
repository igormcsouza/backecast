# AGENTS.md

## What this project is

A small podcast platform (upload an episode → AI generates title, short
description, and resource links → publish → public streaming page), built
by Igor. Originally a guided learning project (the AI wrote every phase
end-to-end while teaching event-driven concepts as it went); the MVP is
now delivered and live — see README.md for the architecture diagram and
current stack. This file now documents ongoing conventions, not a phase
plan.

Stack: Next.js static export (GitHub Pages) · FastAPI on Lambda (Mangum) ·
S3 + CloudFront-free direct streaming · DynamoDB · SQS pipeline · Cognito
(admin auth) · OpenAI transcription (`gpt-4o-mini-transcribe`) + LangChain
metadata chain · CDK in Python · uv · docker-compose + LocalStack.

## Non-negotiable rules

- **uv for everything Python.** Never `pip install`, `poetry`, or bare
  `python` — always `uv add` / `uv run`.
- **Cost guardrails:** everything stays in AWS free tier where possible.
  Forbidden: NAT Gateway, ALB, MSK, Amazon MQ, provisioned concurrency.
  State the cost before creating anything billable (transcription ≈
  $0.003/min ≈ $0.18 per hour-long episode).
- **LangChain only for the worker's metadata chain** (structured output via
  Pydantic, swappable provider) — never as a general wrapper elsewhere.
- **Lambda rules:** no FastAPI `BackgroundTasks`; async work goes through
  SQS; clients initialized at module level; worker must be idempotent
  (check status in DynamoDB before starting work; conditional writes).
- **Async discipline:** no blocking I/O (incl. plain boto3) inside
  `async def`. Blocking work goes in `def` routes (threadpool) or through
  `run_in_threadpool`.
- **Admin auth is Cognito**, not a shared secret — see
  `infra/stacks/auth_stack.py` and `backend/app/core/auth.py`. No
  self-registration anywhere; the single admin user is created by hand in
  the Cognito console. `AUTH_STUB=1`/`NEXT_PUBLIC_AUTH_STUB=1` bypass real
  Cognito for local dev and the E2E suite only (LocalStack Community has no
  Cognito) — never set for a real deploy.
- When teaching or explaining changes touching the async pipeline
  (idempotency, DLQ, visibility timeout, at-least-once delivery), explain
  the "why", not just the "what" — these are deliberate design choices,
  not incidental plumbing.

## Repo layout

```
frontend/   Next.js (static export, TypeScript, Tailwind)
backend/    FastAPI app (uv project) — domain layout below; worker/ inside
infra/      CDK in Python (uv project) — one file per stack in stacks/
e2e/        Playwright in Python (uv project)
docker-compose.yml       LocalStack + api + worker + init (local dev)
docker-compose.e2e.yml   Adds frontend + e2e services (E2E suite only)
scripts/init-localstack.sh   Seeds LocalStack (table, bucket, queues)
README.md   Architecture diagram, stack, deploy notes (start here)
```

## Backend conventions (FastAPI)

- **Domain-based structure**, not file-type-based:
  ```
  backend/app/
  ├── main.py        # app factory, router includes, Mangum handler
  ├── core/           # settings (pydantic-settings), logging, auth dependency
  ├── episodes/
  │   ├── router.py       # thin: HTTP concerns only
  │   ├── service.py      # business logic
  │   ├── repository.py   # all DynamoDB access lives here
  │   ├── schemas.py      # request/response Pydantic models
  │   └── exceptions.py
  └── shared/         # s3 presign helper, sqs client, dynamodb client
  backend/worker/     # separate Lambda: SQS consumer, not part of the API app
  backend/tests/      # mirrors app/ structure
  ```
- **Dependency injection everywhere:** repositories, settings, auth via
  `Depends()`. Module-level *clients* initialized once are fine (Lambda
  best practice) — access them through dependencies, not module globals
  reached into from routes.
- **Pydantic-first at the edges:** every request/response has a schema;
  use `response_model`. Keep DynamoDB item shapes separate from API
  schemas.
- **Settings** via `pydantic-settings`; values from env vars set by CDK;
  secrets from SSM Parameter Store (never in git).
- **Consistent errors:** the custom exception hierarchy in
  `app/core/exceptions.py` + its handler — a stable `{"error": "..."}`
  envelope, not ad-hoc `HTTPException`s.
- **Structured logging** (JSON) with request IDs; no `print`.
- **REST conventions:** plural nouns, correct status codes (201 on
  create), versioned prefix `/api/v1`.

## Infra conventions (CDK, Python)

```
infra/
├── app.py                 # CDK entrypoint: instantiates stacks per stage
├── stacks/
│   ├── data_stack.py       # media bucket, DynamoDB table
│   ├── auth_stack.py       # Cognito User Pool + client (admin auth)
│   ├── api_stack.py        # API Lambda, API Gateway HTTP API
│   └── pipeline_stack.py   # SQS queue + DLQ, worker Lambda, S3 notifications
└── tests/                  # CDK assertions tests (Template.from_stack)
```

- Stages: `prod` (the one, always-on public environment — auto-deploys on
  every push to `main`) and `pr-<number>` (ephemeral preview, deployed
  while its PR is open, destroyed on close — that's the pre-merge testing
  step; there is no separate `dev`). Stage config lives in
  `infra/cdk.json`'s `context` block; `pr-*` stages fall back to `prod`'s
  region.
- Environment config via `cdk.json` context — no hardcoded ARNs.
- Removal policy: `pr-*` stages are `DESTROY` (must tear down cleanly,
  unattended); `prod` is `RETAIN` (never lose real data to an accidental
  `cdk destroy`).
- Deploy auth: a static IAM user (`backecast-github-actions`, in the
  shared `Projects` IAM group), access key stored as GitHub Actions
  secrets — not OIDC federation (this repo briefly used OIDC; switched
  back for consistency with Igor's other projects' CI setup).

## Testing strategy

1. **Unit tests**: pytest, colocated in `backend/tests/`, mirror `app/`.
2. **API integration tests**: `backend/tests/integration/`, run against
   the docker-compose stack (`docker compose run --rm api uv run pytest
   tests/integration`) — real HTTP calls, real LocalStack S3/SQS/DynamoDB,
   AI stubbed (`AI_STUB=1`), auth stubbed (`AUTH_STUB=1`). They hang if run
   outside that compose network (no `api`/`localstack` hostnames to
   resolve) — don't run `uv run pytest` bare from `backend/` expecting
   these to pass.
3. **E2E tests**: Playwright in Python, `e2e/`, against the full
   docker-compose stack including a built frontend. Covers real user
   journeys through the browser.
4. **CDK assertion tests**: `infra/tests/`, `Template.from_stack()`.

## Common commands

```bash
docker compose up -d            # local stack (LocalStack + api + worker)
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
                                 # same, plus makes presigned S3 URLs reachable
                                 # from a browser on the host (needed to test
                                 # real uploads/playback outside the container
                                 # network — see docker-compose.local.yml)
uv run pytest                   # in backend/ (unit only, bare) or infra/
docker compose run --rm api uv run pytest tests/integration  # backend integration
uv run ruff check --fix .       # lint (backend + infra)
uv run uvicorn app.main:create_app --factory --reload   # api only, in backend/
cdk synth | cdk deploy | cdk diff      # in infra/ (CLI installed via npm)
```

## Environment notes

- Local AWS clients use `AWS_ENDPOINT_URL` (set only in compose → LocalStack).
- `AI_STUB=1` locally: worker returns canned transcript + metadata instead
  of calling OpenAI / the LangChain chain.
- `AUTH_STUB=1` (backend) / `NEXT_PUBLIC_AUTH_STUB=1` (frontend) locally:
  admin login/verification uses a fixed local username+password/token
  instead of real Cognito.
- Secrets (OpenAI key, LLM provider key) live in SSM Parameter Store,
  never in git.
