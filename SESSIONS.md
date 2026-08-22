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

## Session 5 — 2026-08-22 — Phase 4: The event pipeline (S3 → SQS → worker Lambda)
**Built:** S3 (`uploads/` prefix) → SQS queue → worker Lambda → DLQ, wired
both in CDK (for AWS) and docker-compose/LocalStack (for local dev). No AI —
the worker only proves the wiring by flipping an episode's status
`uploading → processing → processed-stub`.
- `backend/worker/handler.py`: plain synchronous SQS-batch handler (no async
  — SQS-triggered Lambdas don't need an event loop, so this sidesteps the
  "no blocking boto3 in `async def`" rule entirely instead of relying on
  discipline). Parses the S3 event embedded in each SQS message body,
  derives the episode id from the object key, and moves it through the
  state machine via `_transition()` — a conditional `UpdateItem`
  (`ConditionExpression="#status = :from"`) that no-ops (doesn't raise) if
  the item isn't in the expected "from" state. Returns
  `{"batchItemFailures": [...]}` so only messages that actually failed are
  retried (`ReportBatchItemFailures`), not the whole batch.
- `backend/worker/local_poller.py`: the docker-compose `worker` service's
  entrypoint — polls SQS in a loop and calls the *same* `handler()` Lambda
  would call, deleting only the messages the handler reports as
  successful. This is the "seam" manual.md calls out: local behavior can't
  drift from AWS behavior because the business logic only exists once.
- `backend/app/episodes/schemas.py`: `EpisodeStatus` gains `PROCESSING` and
  `PROCESSED_STUB`.
- `infra/stacks/pipeline_stack.py` (new): DLQ (`maxReceiveCount: 3`), main
  queue (`visibility_timeout` = 180s = 6× the worker Lambda's own 30s
  timeout), worker `PythonFunction` (table read/write only — no S3 access
  needed since the worker never reads the object, only its key), an SQS
  event source mapping (`batch_size=5`,
  `report_batch_item_failures=True`), and an S3→SQS `ObjectCreated`
  notification on `uploads/`. `infra/tests/test_pipeline_stack.py` (7 new
  assertion tests) covers all of the above. `infra/app.py` instantiates it.
  `cdk synth` succeeds for all three stacks; not deployed to real AWS this
  session (that's a separate, Igor-approved action).
- `docker-compose.yml`: new `worker` service (`python -m
  worker.local_poller`), plus two sabotage-toggle env vars
  (`WORKER_SABOTAGE_FORCE_FAILURE`, `WORKER_SABOTAGE_SLEEP_SECONDS`,
  both default off). `scripts/init-localstack.sh` now creates the DLQ +
  queue (mirroring the CDK visibility timeout / maxReceiveCount by hand,
  since the script has no CDK context to import them from) and the S3→SQS
  notification config.
- Tests: `backend/tests/test_worker_handler.py` (unit, in-memory fake
  table — no AWS) covers the happy path, duplicate delivery being a
  no-op, forced failure being reported as a batch item failure, partial
  batch failure only reporting the bad message, and the `s3:TestEvent`
  skip. `backend/tests/integration/test_processing_flow.py` uploads a real
  episode and polls (bounded timeout — no synchronous "done" signal for an
  async pipeline) until status reaches `processed-stub`; passes against
  the full compose stack.
**Decisions:** worker Lambda given no S3 permissions — Phase 4's stub never
reads the uploaded object, only the key embedded in the S3 event, so
granting `s3:GetObject` would be an unused permission (Phase 5's ffmpeg step
will need it, added then). The S3 bucket notification is attached to a
same-named *imported* bucket inside `PipelineStack`
(`s3.Bucket.from_bucket_name`) rather than to the concrete `bucket` construct
passed in from `DataStack` — calling `add_event_notification()` on the real
construct would plant its custom-resource handler in `DataStack`, which
would then need `PipelineStack`'s queue ARN, creating a dependency cycle
with `PipelineStack`'s existing dependency on `DataStack` for the table.
Importing by name keeps the only cross-stack reference one-directional (a
plain bucket-name string). Sabotage hooks (`WORKER_SABOTAGE_*` env vars)
were left in the shipped worker code rather than added-then-reverted by
hand each time — they default to inert, cost nothing in production, and
make the exercises reproducible instead of one-off.
**Learned:** — (Igor to fill in, in his own words — see the sabotage
exercise findings below for the raw material)
**Open questions:** none.
**Next step:** start Phase 5 — AI metadata generation. The worker's stub
middle section (`_transition` → sleep → `_transition`) gets replaced with
real work: ffmpeg preprocessing to compressed mono audio (ship the worker as
a Lambda **container image**, not zip, to bundle ffmpeg), OpenAI
`gpt-4o-mini-transcribe` (~$0.003/min, state cost before the first real
run), then a LangChain metadata chain (`init_chat_model` +
`.with_structured_output()` against a Pydantic model) producing title/
description/resource links. Revisit `WORKER_TIMEOUT` (currently 30s, stub-
sized) and the derived visibility timeout once the ffmpeg+transcribe+LLM
budget is known — Phase 5's own callback to this session's 6× rule. Store
the transcript in S3, not DynamoDB (400KB item limit). Mandatory sabotage
exercise: make the LLM return an invalid resource-link shape and watch
Pydantic validation fail.

### Sabotage exercise findings (factual account — for the Learned line above)

All three run against the real docker-compose + LocalStack stack (not a
simulation), using the shipped `WORKER_SABOTAGE_*` env vars plus direct
`awslocal sqs`/`dynamodb` calls to control and inspect queue state.

1. **Forced failure → retry → DLQ.** Set
   `WORKER_SABOTAGE_FORCE_FAILURE=1` and (to keep the exercise fast)
   temporarily lowered the queue's visibility timeout to 5s. Uploaded one
   episode. The worker logged the same `RuntimeError` three times, roughly
   6 seconds apart (`17:47:07`, `17:47:13`, `17:47:19` — i.e. once per
   visibility-timeout redelivery), each time reporting the message as a
   batch item failure. After the third failure the message stopped being
   redelivered to the main queue and appeared in the DLQ instead, with
   `ApproximateReceiveCount: 4` and `DeadLetterQueueSourceArn` pointing back
   at the main queue — SQS moves a message to the DLQ once its receive
   count exceeds `maxReceiveCount` (3), consistent with the CDK/init-script
   config. The episode's DynamoDB item stayed at `status=uploading` the
   whole time (the forced failure raises before any transition runs), so no
   partial state was left behind either.
2. **Visibility timeout shorter than processing time → duplicate delivery.**
   Set the queue's visibility timeout to 5s and the worker's sabotage sleep
   to 20s (deliberately: sleep > visibility timeout). Uploaded an episode,
   then — since the compose `worker` service is a single-threaded poller
   and can't race against itself — manually invoked `worker.handler.handler`
   a second time (playing the role of a second consumer) against whatever
   the queue handed back once the 5s visibility window expired, while the
   first invocation was still 12 seconds into its 20-second sleep. The
   queue *did* hand the same message back: the second invocation logged its
   own `"processing started"` for the same episode id — duplicate
   processing genuinely occurred, exactly as a too-short visibility timeout
   predicts. But its `uploading → processing` transition immediately hit
   `ConditionalCheckFailedException` (logged as `"transition skipped
   (idempotency guard)"`) because the first invocation had already made
   that transition; the second invocation returned cleanly with no
   exception and no further writes. The item's final DynamoDB state was
   `processed-stub` with a single `updated_at` from the first invocation's
   completion — no corruption, no double-processing side effect, despite
   the duplicate delivery actually happening. Restoring the visibility
   timeout to 180s (the correct 6× value) and repeating the same 8-second
   sleep produced no redelivery at all: only one `"processing started"` log
   line, because the message stayed invisible for the whole processing
   window.
3. **Same message processed twice → idempotency guard holds.** Uploaded an
   episode and let it finish normally (`status=processed-stub`,
   `updated_at=17:57:15.384453Z`). Then manually replayed the identical S3
   event (same bucket/key, a new SQS `messageId`) straight into
   `handler()`, simulating an at-least-once redelivery of an
   already-fully-processed message. The replay logged `"processing
   started"` followed immediately by `"transition skipped (idempotency
   guard)"`, returned `{"batchItemFailures": []}` (no error), and left the
   DynamoDB item completely unchanged — same status, same `updated_at`
   timestamp as before the replay. The conditional write is what makes this
   safe: a second delivery of the same logical event finds the item already
   past the `uploading` state and simply does nothing, rather than
   re-running work or corrupting the record.

## Session 4 — 2026-08-22 — Phase 3: Upload flow (presigned POST)
**Built:** `POST /api/v1/episodes` creates a DynamoDB item (`status=uploading`,
PK/SK=`EPISODE#{id}`, GSI1PK=`EPISODE`) and returns a presigned S3 POST
(`content-length-range` ≤60MB + `Content-Type` conditions). New:
`app/core/auth.py` (`X-Admin-Key` dependency, secret from SSM, cached at
module scope), `app/shared/s3.py` (presigned-POST helper via
`run_in_threadpool` — sync boto3 call, must not block the event loop),
`EpisodesRepository.create()` (conditional `put_item`,
`attribute_not_exists(PK)`). Infra: media bucket CORS now allows `POST`, new
SSM `StringParameter` for the admin key, `ApiStack` grants
`table.grant_read_write_data`, `bucket.grant_put`, `admin_key_param.grant_read`.
`docker-compose.yml`/`scripts/init-localstack.sh` seed the media bucket + a
fixed local admin key (`local-dev-admin-key`). First integration tests in
`backend/tests/integration/test_upload_flow.py` (4 tests: create + DynamoDB
item, real upload to S3 via the presigned response, missing/wrong admin key
→ 401) — pass locally, run via `docker compose run --rm api uv run pytest
tests/integration` (must run inside the compose network — the presigned
URL is signed against `http://localstack:4566`, unreachable from the host).
**Decisions:** wrote the DynamoDB item before generating the presigned POST
(no orphan key without a tracking row, no promise without a signed URL).
Plain SSM `StringParameter` (not `SecureString`) for the dev admin key —
CDK's L2 construct doesn't support `SecureString` directly; fine for a
single dev-only shared secret, real value set manually post-deploy via
`aws ssm put-parameter --overwrite`. Deferred adding `moto` + a unit test for
the repository's conditional-write branch — not a project dependency yet,
and the integration test already exercises the real path against LocalStack;
revisit as a small standalone task, not a Phase 3 blocker.
**Learned:** —
**Open questions:** none.
**Next step:** start Phase 4 — the event pipeline (S3 → SQS → worker Lambda,
DLQ, `maxReceiveCount: 3`). No AI yet — the worker just flips
`uploading → processing → processed-stub`. Concepts: at-least-once delivery,
visibility timeout (≈6× worker timeout), `ReportBatchItemFailures`,
idempotency via conditional writes (reuse the pattern from
`EpisodesRepository.create()`). Three mandatory sabotage exercises per
manual.md §7 Phase 4 — don't skip them.

## Session 3 — 2026-08-22 — Working-agreement change: AI writes backend too
**Built:** nothing code-wise yet — this entry closes the loop on the Phase 2
commit (`af286a3`, FastAPI skeleton on Lambda) that shipped without a
session-log entry, and records a policy change before Phase 3 starts.
**Decisions:** Igor no longer wants to hand-write `backend/`. AI now builds
every phase entirely (backend included, alongside the pre-existing
frontend/e2e/infra exceptions); Igor reviews and uses the result as his
learning base. Updated `CLAUDE.md` and `manual.md` §2 to match.
**Learned:** —
**Open questions:** none.
**Next step:** start Phase 3 — Upload flow (presigned POST), AI-built:
`POST /api/v1/episodes` (presigned POST with `content-length-range`, ~60MB
cap), `X-Admin-Key` auth dependency (secret from SSM), conditional DynamoDB
write with status=`uploading`, first integration tests in
`backend/tests/integration/` against the docker-compose stack.

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
