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
