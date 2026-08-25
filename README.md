# Backecast

A small podcast platform: upload an episode → an async pipeline transcribes
it and has an LLM generate a title, short description, and resource links →
admin reviews/edits → publish → public streaming page.

Live: **https://igormcsouza.github.io/backecast/** (frontend, GitHub Pages) ·
backend API on AWS Lambda + API Gateway (`prod` stage).

## Architecture

```
                                   ┌─────────────────────────┐
                                   │   Next.js static export │
                                   │      (GitHub Pages)     │
                                   └────────────┬─────────────┘
                                                │ HTTPS
                                                ▼
                          ┌──────────────────────────────────────┐
                          │   API Gateway (HTTP API)              │
                          └────────────────────┬───────────────────┘
                                                │
                                                ▼
                          ┌──────────────────────────────────────┐
                          │   API Lambda (FastAPI + Mangum)       │
                          │   backend/app/                        │
                          └───┬──────────────┬───────────────┬────┘
                              │              │               │
                admin routes  │              │               │ public routes
             (Cognito bearer  │              │               │  (no auth)
                     token)   ▼              ▼               ▼
                    ┌─────────────┐  ┌───────────────┐  ┌──────────┐
                    │  Cognito     │  │   DynamoDB    │  │  S3      │
                    │  User Pool   │  │  single table │  │  media   │
                    │ (admin auth) │  │ (episodes +   │  │  bucket  │
                    └─────────────┘  │  job status)  │  └────┬─────┘
                                     └───────────────┘       │
                                                              │ s3:ObjectCreated
                                                              │ (uploads/*)
                                                              ▼
                                                     ┌──────────────────┐
                                                     │   SQS queue      │
                                                     │  (+ DLQ, maxRx=3)│
                                                     └────────┬─────────┘
                                                              ▼
                                                     ┌──────────────────┐
                                                     │  Worker Lambda    │
                                                     │  backend/worker/  │
                                                     │  1. ffmpeg        │
                                                     │     preprocess    │
                                                     │  2. OpenAI        │
                                                     │     transcribe    │
                                                     │  3. LangChain     │
                                                     │     metadata gen  │
                                                     │  4. write status  │
                                                     │     to DynamoDB   │
                                                     └──────────────────┘

Upload flow:
  UI ──(1) POST /episodes ────────► API returns a presigned S3 POST
  UI ──(2) uploads file directly to S3 (uploads/{episode_id}.*)
  S3 ──(3) event notification ────► SQS ────► Worker Lambda
  Worker ─(4) ffmpeg → OpenAI transcribe → LangChain metadata → DynamoDB
  UI ──(5) admin polls GET /episodes/{id}/admin, edits, publishes

Streaming: the episode's media_url served straight from the S3 bucket
(Range requests supported natively) — never through Lambda.
```

**If something's broken, use this diagram to localize it:**
- Public page won't load at all → GitHub Pages / `deploy-frontend` job
  (`.github/workflows/deploy.yml`).
- Public page loads but no episodes / stale API data → API Lambda,
  API Gateway, or DynamoDB — check `deploy-backend`'s CloudWatch logs.
- Admin login fails → Cognito User Pool / User Pool Client
  (`infra/stacks/auth_stack.py`) or `frontend/lib/auth.ts`'s
  `InitiateAuth` call.
- Upload succeeds but episode never leaves `processing`/`transcribing` →
  worker Lambda, SQS queue, or its DLQ (`infra/stacks/pipeline_stack.py`) —
  check the DLQ for stuck messages first.
- Audio won't play → S3 bucket CORS/permissions, not the API.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js (static export), TypeScript, Tailwind — hosted on GitHub Pages |
| Backend | Python 3.12, FastAPI, Mangum, **uv** for dependency management |
| Admin auth | AWS Cognito User Pool (username + password; no self-registration — admin user created by hand in the Cognito console) |
| AI | Transcription: OpenAI `gpt-4o-mini-transcribe` (~$0.003/min). Metadata generation: LangChain (`init_chat_model`, swappable provider — default OpenAI) |
| Data | DynamoDB (single table, on-demand billing), S3 (media) |
| Async pipeline | S3 event → SQS → Worker Lambda, DLQ with `maxReceiveCount=3` |
| Infra | CDK in Python, one stack per concern (`Data`, `Auth`, `Api`, `Pipeline`), parameterized by stage (`prod`/`pr-<n>` — no separate `dev`) |
| CI/CD | GitHub Actions — CI on every PR/push (path-filtered per layer); CD on merge to `main` deploys `prod`, only the layer(s) that changed (backend and/or frontend); ephemeral per-PR preview stacks are the pre-merge testing step |
| Local dev | docker-compose: API (`uvicorn --reload`) + worker + LocalStack (S3, SQS, DynamoDB) |
| Testing | pytest unit + integration (against docker-compose/LocalStack) · CDK assertion tests · Playwright E2E (Python) |

See `CLAUDE.md` for conventions (async discipline, domain layout, uv rules,
cost guardrails) and how to run things locally.

## Deploying

Deploy auth is a static IAM user (`backecast-github-actions`, in the shared
`Projects` IAM group) — its access key lives in this repo's GitHub Actions
secrets (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`). `AWS_DEPLOY_REGION`
is a repo variable (defaults to `sa-east-1` if unset).

- **`prod`**: the one, always-on public environment. Auto-deploys on every
  push to `main`, but only the layer(s) that actually changed — a
  frontend-only change skips the backend CDK deploy and vice versa; a
  docs-only change deploys nothing. There is no separate `dev` — a merged
  PR *is* the release. `workflow_dispatch` (Actions tab → CD → Run
  workflow) force-deploys both layers unconditionally, for the rare case a
  path-filter gap left a change undeployed.
- **PR previews**: `Backecast-pr-<number>-*` stacks, deployed on open/push,
  destroyed unconditionally on PR close — this is the pre-merge testing
  step; review the PR preview's API URL (commented on the PR) before
  merging.

The admin Cognito user is **not** created by CDK — after `AuthStack`
deploys, create the single admin user in the Cognito console (AWS Console →
Cognito → the `backecast-<stage>-admin` pool → Users → Create user), set a
**permanent** password there (not temporary), and use that username to log
into `/admin`.

## Appendix: local-environment options considered but not adopted

Kept here as reminders that these paths exist, in case the current setup
stops being enough.

### 1. Full LocalStack emulation (Lambda + API Gateway)

Right now local dev runs `uvicorn --reload` directly against the FastAPI app
(`create_app()`), bypassing Mangum/Lambda/API Gateway entirely. LocalStack
only emulates the services the app *calls* at runtime (S3, SQS, DynamoDB) —
not the services it's *deployed into*.

LocalStack can also emulate Lambda + API Gateway, so the api container could
run through the exact same deployment topology as production instead of
short-circuiting it.

**Trade-off:** higher fidelity (tests the actual API Gateway → Lambda →
Mangum adapter locally) vs. losing hot reload — every code change would need
a zip rebuild + redeploy into LocalStack's fake Lambda before it's testable,
instead of an instant `--reload`.

### 2. `cdklocal` for the `init` service

`init-localstack.sh` hand-copies the DynamoDB table schema (PK/SK/GSI1) from
`infra/stacks/data_stack.py`. If the CDK stack changes and the script isn't
updated to match, they drift silently.

[`cdklocal`](https://github.com/localstack/aws-cdk-local) (npm package
`aws-cdk-local`) wraps the real `cdk` CLI and redirects its AWS calls to
LocalStack, so `cdklocal deploy` could provision the *same* CDK stack code
locally — no duplicated schema, single source of truth.

**Trade-off:** eliminates drift risk vs. a much slower/heavier `init` step —
full CloudFormation-style deploy (change sets, dependency ordering, stack
events) against LocalStack takes seconds-to-tens-of-seconds, vs. ~1s for a
plain `awslocal dynamodb create-table`. Also pulls in a second toolchain
(Node + `aws-cdk-local`) and a one-time `cdklocal bootstrap` step.

### 3. Cognito emulation for local/E2E auth

LocalStack Community doesn't include Cognito (Pro-only), so local dev and
the E2E suite use a stub login path instead (`AUTH_STUB=1` /
`NEXT_PUBLIC_AUTH_STUB=1` — see `backend/app/core/auth.py` and
`frontend/lib/auth.ts`) rather than a real Cognito call. Revisit if
LocalStack Community ever adds Cognito support, or if a paid LocalStack Pro
license is ever justified for this project.
