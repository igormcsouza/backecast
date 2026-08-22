# PodcastDev — AI-Guided Build Manual

> **Audience of this document:** the AI assistant (Claude Code or similar) guiding Igor through building this project.
> **Read this entire file before the first session. Re-read the "How to teach" section at the start of every session.**

---

## 1. Purpose

Igor is building a small podcast platform as a learning project with production-quality habits. The goals, in priority order:

1. **Learn by doing** — the AI now builds every phase (changed Session 3, 2026-08-22 — Igor's call); Igor reads the result as his learning base instead of typing it himself. The AI still teaches and reviews as it goes.
2. **Learn event-driven architecture** — SQS, idempotency, DLQs, decoupling. This is a core learning objective, not incidental plumbing.
3. **Ship a working MVP** without spending excessive time. Bias toward the simplest thing that works.

**Note on scale:** parts of this plan are deliberately over-engineered for a personal project (DLQs, integration tests, OIDC deploys, layered architecture). That's intentional — the traffic will never justify them, but the *habits* are the product. When Igor points out something is overkill, agree, and explain what real-world problem the pattern exists to solve.

## 2. How to teach (AI behavior rules)

- **AI writes all the code (changed Session 3, 2026-08-22).** Igor gave up writing it himself — he wants working code as a learning base to read, not a blank editor. Build every phase end-to-end (backend included, on top of the pre-existing frontend/e2e/infra exceptions), give Igor a short guided tour of what was built and why, and move on. Still explain concepts as you go — the teaching didn't go away, only the "Igor types it" part did.
- **Review with Igor.** Walk him through what was built against the conventions in §5, so review still happens even though he didn't write it.
- **One step at a time.** Each session has a Definition of Done (§7). Don't jump ahead. If Igor asks about a later phase, answer briefly and return to the current step.
- **Explain the "why" for event-driven concepts.** Whenever the build touches SQS, retries, DLQs, visibility timeouts, or idempotency, pause and teach the underlying concept. These moments are the point of the project.
- **Break things on purpose.** Each phase includes a "Sabotage exercise" — a deliberate failure to trigger and observe. Never skip these.
- **Time-box.** If Igor is stuck on the same issue for ~20 minutes, offer the solution with an explanation. Learning > suffering.
- **Cost discipline.** Before creating any AWS resource, confirm it's in the free tier or state the expected cost. Flag anything with an always-on hourly charge (NAT Gateway, ALB, provisioned concurrency, MSK, Amazon MQ) as **forbidden** in this project.
- **Session log.** At the end of every session, help Igor append a short entry to `SESSIONS.md`: what was built, decisions made, open questions, next step.

## 3. MVP scope

**In scope (v1):**
- Admin can upload a podcast episode (mp3/m4a) through the web UI.
- On upload, an async pipeline: transcribes the audio, then uses an LLM to generate a **title**, a **short description**, and a list of **resource links** (things mentioned in the episode: tools, libraries, articles).
- Admin can review/edit the generated metadata and publish the episode.
- Public page lists published episodes; anyone can stream them in a web player (with seeking).

**Constraint:** episodes are **≤ 25 minutes** (enforced at upload: max duration/file size — see Phase 3). This keeps every episode inside OpenAI's transcription limits after compression, so no audio chunking is needed anywhere.

**Explicitly OUT of scope (v1):** audio transcoding/normalization, user accounts, comments, RSS feed, search, analytics, multiple podcasts/shows, custom domain (optional stretch in Phase 7).

**Admin auth (keep it simple):** a single shared secret sent as `X-Admin-Key` header, stored in SSM Parameter Store, checked by a FastAPI dependency. Public read endpoints are open. Cognito is v2.

## 4. Architecture

```
Next.js (static export) ──► GitHub Pages              [frontend hosting]
        │
        ▼ HTTPS
API Gateway (HTTP API) ──► Lambda (FastAPI + Mangum) [api]
        │                        │
        │                        ▼
        │                   DynamoDB (single table: episodes + job status)
        │
Upload flow:
  UI ──(1) POST /episodes → API returns presigned S3 PUT URL
  UI ──(2) uploads file directly to S3  s3://media-bucket/uploads/{episode_id}.mp3
  S3 ──(3) event notification ──► SQS queue ──► Worker Lambda
  Worker ──(4) starts Amazon Transcribe job, polls/receives completion
  Worker ──(5) calls Anthropic API with transcript → title/description/links
  Worker ──(6) writes metadata + status=review to DynamoDB
  UI  ──(7) admin polls GET /episodes/{id}, edits, publishes

Streaming: CloudFront distribution in front of the media bucket only (Range
requests work out of the box). NEVER serve audio via Lambda or raw S3 URLs.
The frontend does NOT get a CloudFront distribution — a static Next.js
export needs no origin logic GitHub Pages doesn't already give for free
(global CDN, HTTPS, custom domain support).

DLQ: SQS dead-letter queue attached to the worker queue, maxReceiveCount=3.
```

**Why these choices (teach when relevant):**
- Frontend on GitHub Pages, not S3+CloudFront (decided Session 4, 2026-08-22
  — Igor's call, wants a clean shareable link, not a raw CloudFront domain):
  CloudFront's job here is streaming Range requests off the media bucket —
  a static export has no such need, and GitHub Pages already provides a
  CDN, free HTTPS, and custom-domain support at zero cost. One less CDK
  stack, one less thing to misconfigure or pay for.
- Presigned URLs: browser uploads go straight to S3, avoiding Lambda's payload limits and compute costs.
- SQS between S3 and the worker (instead of direct S3→Lambda): buffering, retry control, DLQ, and it's the event-driven lesson vehicle. Map concepts to RabbitMQ vocabulary when teaching (visibility timeout ≈ ack window, DLQ ≈ DLX, SNS fanout ≈ fanout exchange).
- One DynamoDB table, on-demand mode. No SQL, no Alembic — the zhanymkanov DB conventions that assume SQLAlchemy don't apply; the repository-layer conventions still do.

## 5. Stack and conventions

| Layer | Choice |
|---|---|
| Frontend | Next.js (static export, `output: 'export'`), TypeScript, Tailwind |
| Backend | Python 3.12, FastAPI, Mangum, **uv** for dependency management |
| AWS SDK | boto3 in plain `def` routes/services, or aioboto3 in `async def` — never mix (see async rules) |
| AI | Transcription: **OpenAI `gpt-4o-mini-transcribe`** ($0.003/min — ~8x cheaper than AWS Transcribe; Claude has no audio API). Metadata generation: **LangChain** with a swappable chat model (default `langchain-anthropic`, `langchain-openai` one line away) |
| Infra | **CDK in Python** (`aws-cdk-lib`), managed with uv, one stack per environment (`dev`, `prod`) |
| CI/CD | GitHub Actions: CI on every PR (lint, tests, `cdk synth`, frontend build); CD on merge to `main` (backend/infra deploy via OIDC role — no stored AWS keys; frontend deploys to **GitHub Pages** via `actions/deploy-pages`) |
| Local dev | **docker-compose**: API (uvicorn `--reload`) + worker + LocalStack (S3, SQS, DynamoDB) — see "Local development" below |
| Testing | pytest + moto (unit) · API integration tests against docker-compose/LocalStack (**Igor writes, AI helps**) · E2E with **Playwright in Python** (**AI writes entirely**) — see "Testing strategy" |

### FastAPI conventions (from zhanymkanov/fastapi-best-practices + official docs)

The AI must enforce these in every code review:

1. **Async discipline.** `async def` routes must never call blocking I/O (that includes plain boto3). Blocking work goes in `def` routes (threadpool) or through `run_in_threadpool`. If a route is CPU-trivial and calls boto3, prefer plain `def`.
2. **Domain-based structure**, not file-type-based:
   ```
   backend/
   ├── pyproject.toml          # managed by uv
   ├── app/
   │   ├── main.py             # app factory, router includes, Mangum handler
   │   ├── core/               # settings (pydantic-settings), logging, auth dependency
   │   ├── episodes/
   │   │   ├── router.py       # thin: HTTP concerns only
   │   │   ├── service.py      # business logic
   │   │   ├── repository.py   # all DynamoDB access lives here
   │   │   ├── schemas.py      # request/response Pydantic models
   │   │   └── exceptions.py
   │   └── shared/             # s3 presign helper, sqs client, ai/ (transcription client + LangChain metadata chain)
   ├── worker/                 # separate Lambda: SQS consumer (not part of the API app)
   │   └── handler.py
   └── tests/                  # mirrors app/ structure
   ```
3. **Dependency injection everywhere:** repositories, settings, auth via `Depends()`. No module-level globals reached into from routes (module-level *clients* initialized once are fine — that's Lambda best practice — but access them through dependencies).
4. **Pydantic-first at the edges:** every request and response has a schema; use `response_model`. Keep persistence shapes (DynamoDB items) separate from API schemas.
5. **Settings** via `pydantic-settings`, values from environment variables set by CDK; secrets from SSM.
6. **Consistent errors:** a small custom exception hierarchy + exception handlers producing a stable error envelope.
7. **Structured logging** (JSON) with request IDs; no `print`.
8. **Linting:** `ruff` (lint + format) in pre-commit and CI.
9. **REST conventions:** plural nouns, correct status codes (201 on create, 404 via custom exception), versioned prefix `/api/v1`.

### CDK (Python) conventions

Same language as the backend — one toolchain, and Igor reads infra code with the same fluency as app code.

```
infra/
├── pyproject.toml           # uv project: aws-cdk-lib, constructs, pytest
├── app.py                   # CDK entrypoint: instantiates dev/prod stacks
├── stacks/
│   ├── data_stack.py        # media bucket, DynamoDB table (no frontend bucket — see below)
│   ├── api_stack.py         # API Lambda, API Gateway HTTP API
│   └── pipeline_stack.py    # SQS queue + DLQ, worker Lambda, S3 notifications
└── tests/                   # CDK assertions tests (Template.from_stack)
```

- The `cdk` CLI is still Node-based — install it via `npm i -g aws-cdk`; only the construct code is Python.
- Environment config (account, region, stage names) via `cdk.json` context — no hardcoded ARNs.
- Type hints everywhere; ruff covers infra code too.
- Teach `Template.from_stack()` assertion tests when the first stack exists (e.g., assert the DLQ has `maxReceiveCount: 3`).

### uv rule (absolute)

**uv manages everything Python** — `backend/`, `worker/` (part of the backend uv project), `infra/`, and the E2E test project. Never suggest `pip install`, `poetry`, `pipenv`, or bare `python`. All commands run as `uv run <cmd>`; dependencies are added with `uv add`; lockfiles are committed. Lambda packaging uses `uv export`/`uv sync` output.

### LangChain rule (scoped)

LangChain is used **only for the metadata-generation chain in the worker** — not as a wrapper around boto3, not for the API app. Teach it honestly: `init_chat_model` (provider-agnostic), prompt templates, and `.with_structured_output(PydanticModel)` so the LLM's answer is validated before persisting. The learning goal is knowing LangChain well enough to judge when it earns its abstraction on client projects — demonstrate the provider swap (Anthropic ↔ OpenAI) as a one-line change.

### Local development (docker-compose)

Local testing runs entirely in Docker — no dev AWS account needed for day-to-day work:

```yaml
# docker-compose.yml services (conceptual — Igor implements in Phase 0/2)
localstack:   # emulates S3, SQS, DynamoDB (free Community tier)
api:          # backend image, uv run uvicorn app.main:app --reload, code mounted as volume
worker:       # same image, runs a small poll loop consuming the LocalStack queue
init:         # one-shot: awslocal creates the bucket, table, queue + S3→SQS notification
```

- All AWS clients read the endpoint from an env var (`AWS_ENDPOINT_URL`), set only in compose — teach this as the standard LocalStack pattern; unset in real Lambda.
- OpenAI transcription and the LangChain metadata chain are **not** emulated: an env flag (`AI_STUB=1`) makes the worker return canned transcript + metadata locally. Real AI runs only on AWS (or opt-in locally with real API keys).
- On Lambda there's no SQS poll loop (AWS invokes the handler); the local worker wraps the same handler function in a loop — teach this seam explicitly.
- `docker compose up` + `uv run pytest` must be the entire local setup story.

### Testing strategy (three layers, clear ownership)

1. **Unit tests** (Igor writes, AI reviews): pytest + moto, colocated in `backend/tests/`, mirror the `app/` structure. Fast, no Docker needed. Grow with every phase.
2. **API integration tests** (**Igor writes with AI help** — a stated learning goal): pytest suite in `backend/tests/integration/`, runs against the docker-compose stack (real HTTP calls to the API container, real LocalStack S3/SQS/DynamoDB, AI stubbed). Introduced in Phase 3 and extended each phase; the AI teaches fixtures, factories, and how to assert on the async pipeline (poll status with a timeout helper). Run in CI via `docker compose up -d` before pytest.
3. **E2E tests** (**AI writes entirely, Igor only reviews and runs**): Playwright **in Python**, own uv project in `e2e/`. Covers the real user journeys through the browser against the compose stack (or the dev environment). Built in Phase 7 — the AI should produce the whole suite (config, fixtures, page objects, tests) without asking Igor to code.

### Lambda-specific rules
- Initialize boto3/Anthropic clients at module level (outside handler) for warm reuse.
- Keep the API Lambda's dependencies lean (cold starts). The worker Lambda can be heavier.
- Never use FastAPI `BackgroundTasks` on Lambda — execution freezes after the response. All background work goes through SQS.
- Worker handler must be **idempotent**: processing the same S3 event twice must not duplicate episodes or double-charge Transcribe (check status in DynamoDB before starting work; use conditional writes).

## 6. Cost guardrails

- Target steady-state: **< $2/month** + per-episode AI costs.
- Per-episode processing cost: OpenAI `gpt-4o-mini-transcribe` ≈ $0.003/min (**~$0.18 per 60-min episode**) + a few cents of LLM tokens for metadata. (Rejected: AWS Transcribe at $0.024/min — 8x more.) State this to Igor before Phase 5's first real run.
- Forbidden: NAT Gateway, ALB, MSK, Amazon MQ, provisioned concurrency, OpenSearch.
- First action of Phase 1: create an AWS Budget with a $10 alert.

## 7. Build phases

Each phase = one or more sessions. Rules per phase: state the goal → teach the concepts → Igor implements → AI reviews → run the sabotage exercise (where present) → verify Definition of Done → update `SESSIONS.md`.

### Phase 0 — Setup (short)
**Goal:** repo + toolchain ready.
- Monorepo: `frontend/`, `backend/`, `infra/`, `SESSIONS.md`, this `manual.md`.
- `uv init` in `backend/` and in `infra/` (Python CDK per §5); Next.js app in `frontend/` (static export config). Install the CDK CLI (`npm i -g aws-cdk`) and run `cdk bootstrap` on the dev account.
- Pre-commit with ruff (covers `backend/` and `infra/`).
- **docker-compose skeleton**: LocalStack + init service running (`awslocal` health check passes); api/worker services join in Phase 2/4.
- **CI workflow** (`.github/workflows/ci.yml`), runs on every PR and push to `main`, with three parallel jobs: backend (`ruff check` + `uv run pytest`), infra (`ruff check` + `cdk synth` + CDK assertion tests), frontend (`next build`). Concepts to teach: job matrix vs. parallel jobs, dependency caching for uv and npm, path filters so a frontend-only PR doesn't run backend jobs.
**Done when:** all three jobs pass green on a real PR; `cdk synth` works locally.

### Phase 1 — Infra skeleton
**Goal:** CDK stack with the data layer; AWS Budget alert.
- Concepts to teach: CDK constructs/stacks, DynamoDB single-table basics (PK/SK design for episodes), S3 bucket layout (`uploads/`, `media/`), removal policies for dev.
- Build: media bucket, frontend bucket, DynamoDB table (on-demand), outputs.
**Done when:** `cdk deploy` succeeds; Igor can explain the table's key design; budget alert exists.

### Phase 2 — FastAPI skeleton on Lambda
**Goal:** hello-world API deployed and structured correctly.
- Concepts: Mangum, API Gateway HTTP API, Lambda packaging with uv, app factory pattern, settings, logging, the domain layout from §5.
- Build: `GET /api/v1/health`, `GET /api/v1/episodes` (empty list from repository), deployed via CDK. Local dev with `uvicorn --reload`.
- Review focus: layer separation (router → service → repository), DI, async discipline.
**Done when:** endpoint works locally and on AWS; structure matches §5; Igor can explain why the episodes route is `def` not `async def` (boto3).

### Phase 3 — Upload flow (presigned URLs)
**Goal:** create an episode and upload audio directly to S3.
- Concepts: presigned uploads — teach **presigned POST with a `content-length-range` condition** (enforces the max file size server-side; a plain presigned PUT can't) — content-type constraints, the `X-Admin-Key` auth dependency, conditional writes in DynamoDB. Size cap ~60MB (a 25-min mp3 with headroom); the worker double-checks duration and fails to `rejected` status if over the limit.
- Build: `POST /api/v1/episodes` → creates item (status=`uploading`) + returns presigned URL; test upload with `curl`.
- **First integration tests** (Igor writes, AI teaches the setup): compose stack up, real HTTP call creates an episode, upload to LocalStack S3 via the presigned URL, assert the DynamoDB item.
**Done when:** a file lands in `uploads/{episode_id}.mp3` and the item exists with correct status — proven by a passing integration test, locally and in CI.

### Phase 4 — The event pipeline (core learning phase — go slow)
**Goal:** S3 → SQS → worker Lambda, with DLQ. No AI yet; the worker just flips status to `processing` then `processed-stub`.
- Concepts (teach thoroughly): at-least-once delivery, visibility timeout (set ≈ 6× worker timeout), batch size, partial batch failures (`ReportBatchItemFailures`), DLQ with `maxReceiveCount: 3`, idempotency via conditional writes.
- **Sabotage exercises (mandatory):**
  1. Throw an exception in the worker → watch the message retry, then land in the DLQ. Inspect it in the console.
  2. Set visibility timeout *lower* than the worker duration → observe duplicate processing → fix it and add the idempotency guard.
  3. Upload the same file twice → confirm the idempotency guard holds.
**Done when:** pipeline works end-to-end (locally on compose and on AWS); an integration test covers upload → status eventually `processed-stub` (teach the polling-with-timeout assertion); all three sabotage exercises done and written up in `SESSIONS.md` in Igor's own words.

### Phase 5 — AI metadata generation
**Goal:** the worker does real work: preprocess → transcribe (OpenAI) → generate metadata (LangChain) → DynamoDB. Simpler than the AWS Transcribe route: no async job orchestration — the whole pipeline runs inside one worker invocation.
- Concepts:
  - **ffmpeg preprocessing**: the worker converts the upload to compressed mono (e.g., 32kbps mono m4a/ogg — a 25-min episode ≈ 6MB), comfortably inside OpenAI's 25MB / ~25-min limits, so **no chunking is needed**. If duration exceeds the 25-min cap, the worker sets status=`rejected` and stops. The worker Lambda ships as a **container image with ffmpeg** (teach Lambda container images vs zip here). A worker timeout of ~5 min is plenty; revisit the SQS visibility timeout from Phase 4 accordingly — a nice callback lesson.
  - **Transcription**: OpenAI SDK, `gpt-4o-mini-transcribe` (state the ~$0.18/hr cost; `gpt-4o-transcribe` at 2x is the quality upgrade path).
  - **LangChain metadata chain** (per §5 LangChain rule): `init_chat_model`, a prompt template that takes the transcript, `.with_structured_output()` against a Pydantic model (`title`, `description`, `resources: list[Resource]`) — validated before persisting. Demonstrate the Anthropic ↔ OpenAI provider swap.
  - Storing the transcript in S3, not DynamoDB (teach the 400KB item size limit).
- Build: worker state machine: `processing → transcribing → generating → review`. Failures → status=`failed` + DLQ. API keys from SSM.
- **Sabotage exercise:** make the LLM return an invalid resource link shape (tighten the Pydantic model) → watch validation fail → teach retry-with-feedback vs. fail-to-DLQ trade-off.
**Done when:** uploading a real episode produces an AI-generated title, description, and resource links in DynamoDB, at the stated cost.

### Phase 6 — Frontend (AI-built)
**Goal:** the public product. **The AI writes all frontend code**; Igor's involvement is the API contract and infra.
- Igor's part: finalize the public API endpoints the frontend needs (paginated `GET /episodes` with cursor-based pagination via `LastEvaluatedKey` token, `GET /episodes/{id}`), and enable GitHub Pages for the repo (Settings → Pages, source: GitHub Actions — no CDK involved, no frontend bucket/CloudFront distribution).
- AI's part (build without asking Igor to code): admin page (login with admin key, upload with progress via presigned POST, status polling, review/edit metadata, publish) and public page (paginated episode list + HTML5 audio player streaming from the media bucket's CloudFront). Respect static-export constraints (client-side fetching only) and GitHub Pages' subpath serving (`igormcsouza.github.io/backecast/` — set Next's `basePath`/`assetPrefix` accordingly). Keep design minimal; do not gold-plate. Give Igor a 5-minute tour of the structure afterward.
**Done when:** Igor uploads an episode through the browser, publishes it, and streams it from the public GitHub Pages URL on his phone (seeking works).

### Phase 7 — E2E tests (AI-built, Playwright in Python)
**Goal:** a browser-level safety net, produced entirely by the AI.
- The AI creates the whole `e2e/` project (uv, `pytest-playwright`, fixtures, page objects) and the test suite: admin uploads an episode → metadata appears (stubbed AI) → edit → publish → episode visible on the public page → player loads and seeks. Igor's role: review the code, run it, and ask questions — the AI should explain the structure but **not** ask Igor to write these tests.
- Runs against the docker-compose stack (frontend served via `next dev` or a static server container); wire into CI as a job that boots compose first.
**Done when:** `uv run pytest` in `e2e/` passes locally and in CI, and Igor can explain what each test covers.

### Phase 8 — CD: automated deployment (mandatory)
**Goal:** merge to `main` deploys the whole stack; no long-lived AWS keys in GitHub.
- Concepts to teach: **GitHub OIDC → AWS IAM role** (why it replaces access-key secrets; trust policy scoped to this repo and the `main` branch), least-privilege deploy role, `cdk deploy --require-approval never` in CI; the frontend deploy is a **separate, AWS-credential-free job** using GitHub's own Pages deploy action — worth teaching as the contrast case (no OIDC needed because it's not talking to AWS at all).
- Build (`.github/workflows/deploy.yml`, triggered on push to `main`), two jobs:
  1. `deploy-backend`: reuse CI jobs as a required gate → `configure-aws-credentials` with `role-to-assume` (OIDC, no secrets) → `cdk deploy` all stacks to dev.
  2. `deploy-frontend`: needs `deploy-backend` (for the API URL stack output) → `next build` with the API URL baked in → `actions/upload-pages-artifact` + `actions/deploy-pages` (no AWS credentials involved).
- Create the OIDC provider + deploy role **in CDK** (a small `ci_stack.py`), not by hand in the console — this only covers the backend/infra job.
- **Sabotage exercise:** push a commit with a failing test to a branch, open a PR, confirm CI blocks it; then break `cdk synth` on `main` deliberately (in a safe way) and observe the deploy job fail *before* touching AWS.
**Done when:** a one-line change merged to `main` appears on the public site with zero manual steps, and `git grep -i aws_secret` finds nothing.

### Phase 9 — Polish & stretch (optional)
- `prod` stage: same stacks with a `prod` context, deployed via manual `workflow_dispatch` or tag push — teach the dev→prod promotion pattern.
- Ephemeral PR preview environments (Igor already has patterns for this from SoftMedium).
- Custom domain: a CNAME record (Registro.br or any registrar) pointed at GitHub Pages — no Route53/ACM needed for the frontend, GitHub issues the HTTPS cert automatically. Route53/ACM stays relevant only if the API gets a custom domain too (API Gateway custom domain name).
- v2 backlog to record, not build: RSS feed, transcoding/normalization with ffmpeg, EventBridge fan-out (transcript job + RSS rebuild — natural "lesson two" of event-driven), Cognito auth.

## 8. Working agreements

- Git: small commits per step; conventional commit messages; work on branches, merge when a phase is done.
- Every session ends with a `SESSIONS.md` entry and a stated next step, so any future AI session can resume with full context by reading `manual.md` + `SESSIONS.md`.
- If Igor and the AI disagree on an approach, the AI states the trade-offs in two or three sentences and Igor decides. This is Igor's project.
