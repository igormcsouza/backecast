# SESSIONS.md — Build Log

> Append one entry per session, newest at the top. Every entry ends with a clear
> **Next step** so any future AI session can resume by reading `manual.md` + this file.
> The AI helps write the entry at the end of each session; the "Learned" line must
> be in Igor's own words.

## Entry template

```
## Session N — YYYY-MM-DD — Phase X: <short title>
**Built:** what was implemented (files/components, one or two lines)
**Decisions:** choices made and why (or "none")
**Learned:** the key concept of the session, in Igor's own words
**Open questions:** anything unresolved (or "none")
**Next step:** the exact first action of the next session
```

---

## Session 2 — 2026-07-11 — Phase 1: Infra skeleton
**Built:** `infra/stacks/data_stack.py` (media bucket + frontend bucket + DynamoDB
table, PK/SK + GSI1 for published-episode listing, dev removal policy), wired
into `infra/app.py` replacing the Phase 0 placeholder; CDK assertion tests
(`infra/tests/test_data_stack.py`); deployed (`Backecast-dev-Data`, `sa-east-1`);
AWS Budget alert `backecast-monthly`, $5/mo, 80%/100% thresholds to Igor's email.
**Decisions:** infra/ moved from "Igor writes it" to a standing AI-built exception
(alongside frontend/ and e2e/) — Igor's call, updated in `manual.md` §2 and
`CLAUDE.md`. Budget threshold set to $5 (Igor's preference, tighter than the
manual's default $10).
**Learned:** "When I want to create the CDK code to deploy stuff to AWS I need
the stacks files where I describe properly the infrastructure I want to run,
then I also need the cdk.json that configures the stages I need (prod, dev,
staging), and then the app.py which is the entry point to gather all context
information and shove into the stacks."
**Open questions:** none — confirmed both buckets and the DynamoDB table are
correctly empty right now (schema/containers only; writes start Phase 3,
frontend sync starts Phase 6).
**Next step:** start Phase 2 — FastAPI skeleton on Lambda. Concepts: Mangum,
API Gateway HTTP API, Lambda packaging with uv, app factory pattern, settings,
logging, domain layout from manual.md §5. Build `GET /api/v1/health` and
`GET /api/v1/episodes` (empty list), deployed via a new `api_stack.py`. This
phase is Igor's to write — backend stays the core learning surface.

## Session 1 — 2026-07-11 — Phase 0: Setup
**Built:** monorepo layout (`frontend/`, `backend/`, `infra/`); `uv init` in
`backend/` and `infra/` (Python 3.12, ruff+pytest dev deps); Next.js static-export
skeleton in `frontend/` (`output: "export"`, builds clean); root
`.pre-commit-config.yaml` (ruff check+format on backend/infra, generic hygiene
hooks), hook installed; `docker-compose.yml` skeleton (LocalStack S3/SQS/DynamoDB
+ init placeholder), verified healthy; CI workflow `.github/workflows/ci.yml`
with a `changes` job (dorny/paths-filter) gating three parallel jobs
(backend/infra/frontend), uv+npm dependency caching; AWS CDK CLI installed,
`cdk bootstrap` run on account `693473496042` region `sa-east-1`; `infra/app.py`
+ `cdk.json` with a placeholder stack proving `cdk synth` works end-to-end
(real stacks start Phase 1).
**Decisions:** region `sa-east-1` (Igor's call, latency over `us-east-1`'s
slightly lower cost). Frontend and infra toolchain scaffolding built by AI as
zero-learning-value boilerplate per manual.md §2 — Phase 1 onward, Igor writes
the actual CDK stack contents.
**Learned:** —
**Open questions:** none.
**Next step:** start Phase 1 — CDK data stack (media bucket, frontend bucket,
DynamoDB single table on-demand with PK/SK design for episodes), plus the AWS
Budget $10 alert (manual.md §6/§7 Phase 1).

## Session 0 — (not started)
**Built:** nothing yet — repo scaffolding pending.
**Decisions:** stack and plan locked in `manual.md` (Lambda + SQS pipeline, CDK in
Python, uv everywhere, docker-compose + LocalStack for local dev, OpenAI
`gpt-4o-mini-transcribe` for transcription + LangChain metadata chain, Playwright/
Python E2E written by the AI).
**Learned:** —
**Open questions:** none.
**Next step:** start Phase 0 — create the monorepo layout (`frontend/`, `backend/`,
`infra/`, `e2e/`), `uv init` the Python projects, Next.js static-export app, ruff
pre-commit, docker-compose skeleton with LocalStack, and the CI workflow.
