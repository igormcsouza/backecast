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

## Session 8 — 2026-08-22 — Phase 7: E2E tests (Playwright, Python)

**Built:** the whole `e2e/` uv project (AI-authored end to end, per
CLAUDE.md/manual.md — Igor's role is to review and run it), plus what it
took to actually give it something real to drive.

- `e2e/pyproject.toml`: `pytest`, `pytest-playwright` (pulls in
  `pytest-base-url`), `httpx`, `ruff` (dev). `addopts = "--browser
  chromium"` — headless Chromium only, stated explicitly (see
  `conftest.py`'s docstring for why one browser target is enough for this
  MVP).
- `e2e/conftest.py`: `base_url` (from `FRONTEND_URL`), `admin_key` (from
  `ADMIN_KEY`, defaults to the seeded `local-dev-admin-key`), `api_url`,
  and `tiny_audio_file` — a real ~3s silent mp3 generated at test time via
  ffmpeg's `lavfi` silence source (mirrors
  `backend/tests/integration/conftest.py`'s `tiny_audio_bytes` fixture and
  exists for the identical reason: the worker's real ffprobe/ffmpeg step
  rejects fake bytes), returned as Playwright's `set_input_files`
  dict shape (in-memory, no temp file).
- `e2e/pages/`: three small page objects (`AdminPage`, `ReviewPage`,
  `PublicHomePage`/`PublicEpisodePage`) — locators plus the handful of
  actions a test performs, deliberately thin (no result-object/builder
  layers) for an app this size.
- `e2e/tests/`: `test_admin_login.py` (wrong key rejected, correct key
  reaches the dashboard), `test_public_page.py` (home page renders; an
  unknown episode id 404s, covering the "never confirm an unpublished
  episode exists" contract for the "doesn't exist" half), and
  `test_episode_flow.py::test_upload_edit_publish_and_stream` — the full
  journey from manual.md's Phase 7 spec in one test (upload -> stubbed AI
  metadata appears -> not yet public -> edit -> still not public -> publish
  -> visible on the public page -> player loads and **seeks**, verified by
  setting `audio.currentTime` after `loadedmetadata` and reading it back,
  which only works because the presigned S3 GET URL actually serves byte-
  range requests — see Session 7's streaming decision).
- `frontend/Dockerfile` (new, E2E-only — not used by the real Phase 8
  deploy, which pushes the static export straight to GitHub Pages):
  `npm ci && npm run build` with `NEXT_PUBLIC_API_URL` baked in at build
  time, then serves `out/` with `serve` (no `-s`/SPA-fallback — this is a
  multi-page static export, not a single-page app).
- `e2e/Dockerfile`: based on `mcr.microsoft.com/playwright/python`
  (Chromium + all its OS deps already installed and version-matched to the
  pinned `playwright` package) with `uv` layered on top, plus `apt-get
  install ffmpeg` for the `tiny_audio_file` fixture.
- `docker-compose.e2e.yml` (new override, not merged into the base
  compose file): adds `frontend` and `e2e` services to the same
  compose network `localstack`/`api`/`worker` already share.
- `.github/workflows/ci.yml`: new `e2e` job (boots the compose stack with
  the override, waits for `/api/v1/health` and the frontend root to answer,
  runs `docker compose run --rm e2e`, dumps logs and tears down with
  `-v` on any outcome), gated on a new `e2e` path filter covering
  `e2e/**`, `backend/**`, `frontend/**`, both compose files, and
  `scripts/**`.

**Decisions:**
- **The suite runs as a container on the compose network, not from the
  bare host.** Session 7's "Open questions" already flagged this: presigned
  S3 URLs the backend hands back are signed against
  `http://localstack:4566`, a hostname that only resolves inside the
  compose network's internal DNS. A browser on the host (or a Playwright
  process launched from the host) can reach the frontend's mapped port
  fine, but every `<audio src=...>` and every upload POST would 404/fail to
  resolve the moment it touched a presigned URL. Running both the frontend
  build *and* the Playwright-driven browser as containers on that same
  network — the same "join the network, use service-name hostnames"
  pattern `backend/tests/integration/` already uses for `httpx` — sidesteps
  this entirely and, as a bonus, exercises the *exact* URLs a real browser
  in a real deployment would receive, not a workaround shaped around the
  sandbox. Verified this is a real bug, not a hypothetical: the first
  attempt using a plain `playwright install --with-deps chromium` on the
  bare host failed outright (no passwordless `sudo` for the apt
  dependencies in this sandbox) — using the official Playwright Docker
  image sidesteps that too, for free.
- **Frontend served via a dedicated `frontend/Dockerfile` (E2E-only), not
  `next dev` or `next start`.** `next start` doesn't apply to an
  `output: 'export'` build (there's no Node server artifact to start) and
  `next dev` would mean testing an unoptimized dev-mode bundle instead of
  the actual static export GitHub Pages will serve in Phase 8. A plain
  `serve out/` after `npm run build` tests the real artifact.
- **`docker-compose.e2e.yml` as an override, not merged into
  `docker-compose.yml`.** Keeps `docker compose up -d` — the command
  Igor's used since Phase 0 for local dev — unchanged; the E2E stack (a
  one-shot frontend build + a one-shot test container) is opt-in via
  `-f docker-compose.yml -f docker-compose.e2e.yml`.
- **One big flow test, not five small ones, for the actual journey.** Every
  step after the upload genuinely depends on state the previous step left
  behind (can't publish before `review`, can't check the public page
  without a real published episode) — splitting it up would mean each
  "test" quietly re-running the same setup or sharing state through an
  awkward fixture. The parts that *do* stand alone (the login gate, the
  404-for-unknown-id contract) got their own small, fast test files instead.
- **CI job gated on a wide path filter** (`e2e/**` plus `backend/**` plus
  `frontend/**` plus both compose files) rather than just `e2e/**` — a
  backend or frontend change is exactly the kind of thing this suite exists
  to catch, so scoping the filter to only `e2e/**` would silently skip the
  job on the changes that matter most.
- Captured the just-created episode's id from the real `POST
  /api/v1/episodes` network response (`page.expect_response`) instead of
  scraping it from the DOM afterward — the review queue can (and, once the
  suite has run more than once against the same LocalStack volume, does)
  contain other episodes with the identical stubbed title, so the id is the
  only thing that reliably identifies *this* run's upload.

**A real bug found while wiring the flow (not fixed here, left for Igor to
weigh in on):** `frontend/app/admin/page.tsx`'s `UploadStatus` component
calls its `onDone()` callback the instant the polled status leaves
`IN_FLIGHT_STATUSES` — which unmounts `UploadStatus` (clearing
`activeUploadId`) in the very same render that status becomes `review`. Its
own `{status === "review" && <Link>Review now</Link>}` branch is therefore
dead code: it can never actually render, because the component holding it
is gone before that branch's condition is ever true. Nothing breaks — the
episode still lands correctly in the review-queue list below, which is
what the E2E suite ended up waiting on instead — but the "Review now"
shortcut Igor would see mid-poll never fires. Small, cosmetic, and outside
the "actually blocks the E2E suite" bar this task set for touching
`frontend/` code, so left as a note rather than a fix.

**Learned:** _(Igor fills this in)_

**Open questions:**
- The suite was verified fully working (`docker compose -f
  docker-compose.yml -f docker-compose.e2e.yml run --rm e2e`, 5/5 passed,
  run twice in a row including the full upload -> publish -> stream -> seek
  path) — no environment blocker to flag. The one real obstacle hit along
  the way (host `sudo` unavailable for `playwright install --with-deps` in
  this sandbox) is exactly what steered the "run as a container" decision
  above, and is very likely representative of most CI runners too, not
  just this sandbox — that's a second reason to keep the container-based
  approach even once Igor is running this on his own machine.
- The "Review now" dead-code link (see above) — worth a one-line fix
  someday (swap the order: render before calling `onDone()`, or drop the
  link and rely on the queue), but not urgent and not done here.
- `docker-compose.e2e.yml` maps the frontend to host port 3300 purely for
  optional manual sanity-checking; nothing in the suite depends on it (the
  `e2e` container always talks to `frontend:3000` over the compose
  network).

**Next step:** Phase 8 — CD: automated deployment. Per manual.md: GitHub
OIDC -> AWS IAM role (no long-lived AWS keys in GitHub), a
`.github/workflows/deploy.yml` with `deploy-backend` (`cdk deploy` via
OIDC) and `deploy-frontend` (needs `deploy-backend` for the API URL stack
output; `next build` with `NEXT_PUBLIC_API_URL`/`NEXT_BASE_PATH=/backecast`
baked in, then `actions/upload-pages-artifact` + `actions/deploy-pages` —
no AWS credentials involved in that job at all, worth teaching as the
contrast case), and creating the OIDC provider + deploy role in CDK
(`infra/stacks/ci_stack.py`) rather than by hand in the console. Read
manual.md's Phase 8 section in full before starting; Igor's out-of-band
prerequisite is enabling GitHub Pages (repo Settings -> Pages, source:
GitHub Actions) if not already done from Phase 6.

---

## Session 7 — 2026-08-22 — Phase 6: Frontend (admin + public pages)
**Built:** the whole `frontend/` app (Next.js App Router, static export,
TypeScript, Tailwind) plus the backend read/edit/publish routes it needs.

Backend (`backend/app/episodes/`):
- `schemas.py`: `EpisodeStatus` gains `PUBLISHED`. `GetEpisodeSchema` gains
  `resources: list[Resource] = []` — the worker has written resources to
  DynamoDB since Phase 5, but no schema ever surfaced them; the review view
  needs to show/edit them. New `UpdateEpisodeRequest` (all fields optional —
  PATCH only touches what's given) and `PaginatedEpisodesResponse`
  (`items` + opaque `cursor`).
- `repository.py`: `get()`, `update()` (generic partial `SET`, placeholder-
  based like the worker's `_transition()`), `publish()` (conditional
  `review → published`, same idempotency primitive as every other
  transition in this codebase), `list_by_status()`, `list_published_page()`
  (cursor pagination — see Decisions). Needed `from __future__ import
  annotations` at the top: defining a method literally named `list` earlier
  in the class body shadows the builtin for every `-> list[...]`
  annotation declared afterward in the same class (`TypeError: 'function'
  object is not subscriptable` at import time) — PEP 563 defers annotation
  evaluation and sidesteps it.
- `service.py` / `router.py`: new routes — `GET /episodes` (public,
  paginated, `status=published` only), `GET /episodes/{id}` (public, 404s
  for missing *and* unpublished so it can never confirm an unpublished
  episode's existence), `GET /episodes/admin` (admin, optional
  `?status=` filter — the review queue), `GET /episodes/{id}/admin` (admin,
  any status — status polling + review view), `PATCH /episodes/{id}`
  (admin, edit metadata, 409 unless `status=review`), `POST
  /episodes/{id}/publish` (admin, `review → published`, 409 otherwise).
  Removed the old do-nothing `PUT` stub (superseded by `PATCH`).
- `shared/s3.py`: `create_presigned_get()` — same `run_in_threadpool`
  treatment as the existing presigned-POST helper.
- New integration tests: `tests/integration/test_public_episodes_flow.py`,
  `tests/integration/test_episodes_admin_review_flow.py` (23 tests total in
  the suite now, all passing via `docker compose run --rm api uv run
  pytest tests/integration`) — episodes are seeded directly into DynamoDB
  rather than run through the real pipeline, since these tests are about
  the new routes' filtering/auth/status-transition guards, not the AI
  pipeline `test_processing_flow.py` already covers.

Frontend (`frontend/`, all new except `next.config.ts`/`layout.tsx`/`page.tsx`,
which had a Phase-0 skeleton):
- `lib/types.ts`: hand-written mirror of the Pydantic schemas (no codegen).
- `lib/api.ts`: fetch wrapper (`NEXT_PUBLIC_API_URL`, `X-Admin-Key` header
  when given, JSON error unwrapping into `ApiError`) plus
  `uploadToPresignedPost()` (XHR, not `fetch`, specifically for
  `xhr.upload.onprogress` — `fetch`'s upload-progress story is still
  inconsistent across browsers).
- `lib/admin-key.ts`: localStorage get/set/clear for the admin key, guarded
  with `typeof window` checks — `output: 'export'` still statically
  prerenders "use client" components to HTML at build time in Node, where
  there's no `window`.
- `app/page.tsx`: public episode list, cursor "Load more".
- `app/episode/page.tsx`: public detail + `<audio controls>` player + resource
  links. Takes `?id=` as a query param, not a Next.js dynamic route segment
  (`[id]`) — static export needs `generateStaticParams` for those, and
  episode ids don't exist at build time. Wrapped in `<Suspense>`
  (`useSearchParams()` requires it even for a fully client-rendered page).
- `app/admin/page.tsx`: login gate (key held in localStorage, validated
  against `GET /episodes/admin` on mount so a stale key doesn't look
  "signed in" until the first real action fails), upload form (presigned
  POST + XHR progress bar), post-upload status poller (2s interval, 5min
  timeout — same polling-with-timeout shape as the backend's own
  integration tests, driven from the browser instead of pytest), review
  queue list.
- `app/admin/review/page.tsx`: edit form (title/description/resources,
  disabled once no longer `status=review`) + Save (`PATCH`) + Publish
  (`POST .../publish`) buttons. Same `?id=` + `Suspense` pattern as the
  public detail page.
- `next.config.ts`: `basePath`/`assetPrefix` from a `NEXT_BASE_PATH` build
  env var (unset locally; the Phase 8 deploy workflow sets it to
  `/backecast` for GitHub Pages' subpath serving).
- `.env.example` (committed) / `.env.local` (gitignored, `NEXT_PUBLIC_API_URL`
  pointed at `http://localhost:8989`, docker-compose's host-mapped `api`
  port) — had to add `!.env.example` to `.gitignore`, since create-next-app's
  default `.env*` glob would've swallowed it too.

**Decisions:**
- **Streaming: presigned GET, not CloudFront.** `EpisodesService._with_audio_url()`
  swaps each episode's `audio_key` for a fresh presigned S3 GET URL
  (1h expiry) at read time, for both the public and admin routes. Chosen
  over standing up a CloudFront distribution in front of the media bucket:
  zero new billable resources, reuses the presigned-URL pattern already
  established for uploads (`shared/s3.py`), and — the thing that actually
  matters for "Done when: seeking works" — a presigned S3 GET already
  serves byte-range requests with no extra configuration, which is what
  makes an HTML5 `<audio>` scrub bar work. Trade-off, worth revisiting
  later: the URL expires (fine — it's re-signed on every page load) and
  isn't edge-cached (fine at MVP traffic; CloudFront's free tier — 1TB
  egress/month for the first 12 months, then per-GB after — would still be
  cheap if this ever needs to change, and CloudFront isn't on CLAUDE.md's
  forbidden list, just judged unnecessary for now). **No infra/CDK changes
  in this phase, no new billable resource.**
- **Pagination: reuse GSI1 + FilterExpression, not a new status-keyed GSI.**
  `list_published_page()` queries the same `GSI1` (`GSI1PK="EPISODE"`,
  sorted by `{created_at}#{id}`) every other list already uses, filtering
  to `status=published` server-side instead of adding a `GSI2` keyed by
  status. The honest trade-off: DynamoDB's `Limit` caps items *scanned*
  per call, not items *returned* after the filter, so a page can come back
  with fewer than the requested `limit` (even zero) while `cursor` is still
  non-`None` — the client just asks again (the public list page's cursor
  loop already does this transparently). Rejected the `GSI2` alternative
  because every status transition (the worker's `_transition()`, this
  phase's new `publish()`) would then have to keep a second index
  attribute in sync, and this table's episode count is nowhere near where
  that scan waste would matter. Revisit if the catalog grows large.
- **Cursor shape:** opaque, base64-encoded JSON wrapping DynamoDB's raw
  `LastEvaluatedKey` (`PK`/`SK`/`GSI1PK`/`GSI1SK`) — clients pass it back
  verbatim, never construct or decode it, so the DynamoDB key shape never
  leaks into the API contract.
- **Episode id in the URL as a query param, not a dynamic route segment,**
  on both the public detail page and the admin review page — the standard
  reason static export can't `generateStaticParams` ids it doesn't know
  about at build time.
- Admin auth stays exactly as simple as the spec asks: one shared key,
  typed once, held in `localStorage`, sent as `X-Admin-Key`. No session,
  no expiry, no rotation UI — consistent with the backend's existing
  single-SSM-parameter admin key story.

**Learned:** _(Igor fills this in)_

**Open questions:**
- Full browser click-through (upload → review → publish → stream) wasn't
  possible in this sandbox: the presigned POST/GET URLs LocalStack signs
  point at `http://localstack:4566`, which only resolves *inside* the
  compose network, not from a browser on the host — the same limitation
  the Phase 3 integration tests' docstring already calls out for
  `httpx`. Validated instead via `docker compose run --rm api uv run
  pytest tests/integration` (23/23 passing, including all new Phase 6
  tests) plus a clean `npm run build` (both with and without
  `NEXT_BASE_PATH` set). Igor should do one real click-through once the
  stack is deployed (or by running the frontend inside the compose network,
  e.g. `docker compose run` with an extra service — not set up here, kept
  minimal per the "don't gold-plate" instruction).
- No rate limiting or expiry warning on presigned GET URLs — a very long
  playback session (>1h) would need the page reloaded to get a fresh URL.
  Not addressed; low priority for MVP traffic.

**Next step:** Phase 7 — E2E tests (Playwright, in a new `e2e/` uv project,
AI-built per manual.md). Before that, Igor's out-of-band steps to actually
try Phase 6: (1) enable GitHub Pages (repo Settings → Pages, source:
GitHub Actions — no CDK involved); (2) `cdk deploy` the stacks once ready to
get a real API Gateway URL; (3) set `NEXT_PUBLIC_API_URL` in
`frontend/.env.local` (local dev) or as a build-time env var in the future
CI deploy workflow (Phase 8) to that URL; (4) `NEXT_BASE_PATH=/backecast`
for the GitHub Pages build specifically. Read `manual.md`'s Phase 7 section
in full before starting.

---

## Session 6 — 2026-08-22 — Phase 5: AI transcription + LangChain metadata generation
**Built:** the worker's Phase 4 stub middle (`processing` → sleep →
`processed-stub`) is replaced with the real pipeline: ffmpeg preprocessing →
OpenAI transcription → LangChain metadata chain → DynamoDB, all inside one
synchronous worker invocation (no async job orchestration / Step
Functions). State machine grows to
`uploading → processing → transcribing → generating → review`, with
`processing → rejected` as a duration-cap side exit and `→ failed` reachable
from any in-flight state.
- `backend/worker/audio.py` (new): ffmpeg preprocessing, two plain
  `subprocess` calls (`ffprobe` for duration, `ffmpeg` for a 32kbps-mono
  transcode) — no `ffmpeg-python` dependency. `probe_duration_seconds()`
  runs *before* any transcode, so an over-length upload (>25 min, the
  transcription-length cap) costs nothing beyond the S3 download.
- `backend/worker/transcription.py` (new): OpenAI SDK,
  `gpt-4o-mini-transcribe`. API key from SSM (`OPENAI_API_KEY_PARAM_NAME`),
  fetched once and cached at module scope, same pattern as `app/core/auth.py`'s
  admin-key cache. `AI_STUB=1` short-circuits before any SSM read or network
  call and returns a canned transcript string.
- `backend/worker/metadata.py` (new): the one and only LangChain usage in
  the codebase (per CLAUDE.md's rule) — `init_chat_model(model=settings.llm_model)`
  + `.with_structured_output(EpisodeMetadata)`. `settings.llm_model` is a
  `"<provider>:<model>"` string (e.g. `openai:gpt-4o-mini` or
  `anthropic:claude-3-5-haiku-latest`) — swapping providers is an env var
  change, this file never imports a provider-specific chat-model class.
  `AI_STUB=1` validates a canned payload through the real `EpisodeMetadata`
  Pydantic model instead of calling an LLM. Also owns the Phase 5 sabotage
  hook, `WORKER_SABOTAGE_INVALID_METADATA=1` (same pattern as Phase 4's
  `WORKER_SABOTAGE_*` toggles).
- `backend/app/episodes/schemas.py`: `EpisodeStatus` gains `TRANSCRIBING`,
  `GENERATING`, `REVIEW`, `REJECTED`, `FAILED` (drops `PROCESSED_STUB`,
  fully superseded). New `Resource` (`label`, `url: HttpUrl`) and
  `EpisodeMetadata` (`title`, `description`, `resources: list[Resource]`)
  models — `HttpUrl` is the validation the sabotage exercise leans on.
- `backend/worker/handler.py`: `_transition()` generalized to accept
  `extra_attributes`, so the final `generating → review` transition writes
  title/description/resources atomically with the status change (via
  placeholder-based expression-attribute names, `#a0`/`:v0`-style, to stay
  reserved-word-safe for arbitrary future field names). The big
  `if status == X` chain was split into one `_advance_*()` function per
  stage (`_advance_uploading/_processing/_transcribing/_generating`)
  orchestrated by `_run_pipeline()`, both to keep `ruff`'s C901 complexity
  check happy and because each stage function is independently the unit the
  resumability story (see Decisions) is about. Any exception, at any stage,
  is caught once at the top (`_process_s3_record`), best-effort-transitions
  the episode to `failed` (re-reading current status rather than trusting a
  captured variable — see Decisions), and re-raises so the SQS message is
  reported failed and Phase 4's retry/DLQ mechanics take over unchanged.
- `backend/worker/Dockerfile` (new): the worker Lambda ships as a
  **container image**, not a zip (unlike `ApiFunction`, still a
  `PythonFunction`) — it needs the `ffmpeg`/`ffprobe` *binaries*, which
  aren't a `uv add`-able Python package and are an awkward fit for a Lambda
  Layer at this size. Base image `public.ecr.aws/lambda/python:3.12` +
  a static ffmpeg build (Amazon Linux's default repos don't ship it) + `uv`
  copied in as a binary (not `pip install uv`) to resolve/install deps.
  Built and smoke-tested locally (`docker build`, confirmed `ffmpeg`/`ffprobe`
  on PATH and `worker.handler.handler` importable) — not pushed anywhere.
- `backend/Dockerfile` (the api/worker-shared local-dev image): gained
  `apt-get install ffmpeg` so `docker compose`'s `worker` service runs the
  *real* ffmpeg step locally too, not a mock of it — same
  business-logic-only-exists-once philosophy as `worker/local_poller.py`.
- `infra/stacks/pipeline_stack.py`: `WorkerFunction` is now a
  `DockerImageFunction` (`worker/Dockerfile`, build context `backend/`),
  `WORKER_TIMEOUT` raised 30s → 5 minutes (ffmpeg + OpenAI + an LLM call in
  one invocation needs minutes, not seconds), which — via the existing 6×
  derivation — raises `VISIBILITY_TIMEOUT` to 30 minutes: the Phase 4
  lesson revisited on purpose, same formula, new inputs. Memory bumped
  256MB → 1024MB (ffmpeg + buffering an episode in `/tmp`). New grants:
  `bucket.grant_read(..., "uploads/*")`, `bucket.grant_put(..., "transcripts/*")`
  (scoped to key prefixes, not a blanket read/write), plus
  `grant_read()` on two new SSM parameters.
- `infra/stacks/data_stack.py`: two new placeholder `StringParameter`s,
  `/backecast/{stage}/openai-api-key` and `/backecast/{stage}/llm-api-key`
  — same pattern as the Phase 3 admin key (Igor sets real values post-deploy
  via `aws ssm put-parameter --overwrite`; nothing here is a real secret).
  Two separate params, not one shared key, because the provider-swap seam
  means the metadata-chain key can belong to a different provider than the
  transcription key.
- `infra/tests/test_pipeline_stack.py` / `test_data_stack.py`: updated for
  the container-image Lambda (`PackageType=Image`, 300s timeout), the new
  visibility timeout (1800s), the S3 read/write grants, the two new SSM
  parameters, and the two new `ssm:GetParameter` policy statements.
  `cdk synth --all` succeeds; not deployed to real AWS this session.
- `backend/tests/test_worker_handler.py`: rewritten for the new terminal
  state (`review`, not `processed-stub`) plus new cases — resuming from
  `transcribing` (redoes ffmpeg, no local state survives a fresh
  invocation), resuming from `generating` (re-reads the transcript from S3
  instead), the `rejected` duration-cap path, a metadata-generation failure
  landing on `failed`, and the sabotage case itself (below). ffmpeg/S3 are
  monkeypatched at the handler's own helper boundary; transcription/metadata
  are deliberately left real (AI_STUB=1 makes them free and networkless), so
  these tests cover the actual Pydantic-validation and DynamoDB-write code,
  not a re-implementation of it.
- `backend/tests/test_worker_audio.py`, `test_worker_transcription.py`,
  `test_worker_metadata.py` (new): unit coverage for the three new modules
  in isolation — mocked `subprocess.run` for ffmpeg, mocked SSM/OpenAI
  client for transcription, mocked `init_chat_model` for the provider-swap
  seam, and the sabotage payload's Pydantic rejection.
- `backend/tests/integration/test_processing_flow.py`: rewritten to poll
  for `review`, assert the AI-generated (stubbed) title/description/resources
  landed in DynamoDB, and assert the transcript object exists in S3. Needed
  *real* (if tiny and silent) audio — Phase 4's `b"fake-audio-bytes"` fixture
  doesn't survive real `ffprobe`/`ffmpeg` — so a new `tiny_audio_bytes`
  fixture in `tests/integration/conftest.py` generates a ~1s silent mp3 via
  ffmpeg's `lavfi` source at test time (the `api` container has ffmpeg now
  too, for exactly this).
- `backend/tests/conftest.py`: sets `AI_STUB=1` globally
  (`os.environ.setdefault`) before any test module can import
  `worker.transcription`/`worker.metadata` — belt-and-suspenders with
  docker-compose's own `AI_STUB=1` default, so no automated test run, local
  or CI, can ever place a real network call to OpenAI or Anthropic.
- `docker-compose.yml` / `scripts/init-localstack.sh`: `worker` service
  gets `AI_STUB=${AI_STUB:-1}`, the two new SSM param-name env vars, and the
  new `WORKER_SABOTAGE_INVALID_METADATA` toggle; the init script seeds
  placeholder values for the two new SSM parameters and updates the local
  queue's hand-rolled `VisibilityTimeout` literal to 1800 (mirroring
  `pipeline_stack.py`'s new derivation, per the existing "if you change one,
  change the other" comment there).

**Decisions:** post-merge code review (Igor's request, before Phase 6 starts)
found and fixed three real bugs on top of the build described below: (1)
`BATCH_SIZE=5` with `WORKER_TIMEOUT=5min` meant a batch could legitimately
need ~25 minutes processed sequentially while the Lambda itself got killed
at 5 — batch size dropped to 1 so the worker timeout bounds a single
invocation's worst case exactly; (2) losing the `processing → transcribing`
idempotency race left the loser's ffmpeg-compressed file leaked in `/tmp`
across warm-container reuse — now cleaned up immediately on a lost race;
(3) a duration-cap failure hit on a *resumed* `transcribing` stage (no local
file, redoing the ffmpeg step) fell through to `failed` instead of
`rejected` like the first-pass check — now caught the same way on both
paths. See commit `6c0e33c`.

resumability is coarse-grained, not fully exactly-once. Every
`_advance_*()` stage re-derives its inputs from durable storage (S3) rather
than trusting anything a previous, possibly-crashed invocation left in
memory — a fresh Lambda container has an empty `/tmp`. The one deliberate
optimization: the full transcript is written to S3 *before* the
`transcribing → generating` transition, so a crash between those two stages
resumes by re-reading the already-paid-for transcript instead of re-paying
OpenAI to transcribe the same audio again. A crash *during* transcription
itself has no such checkpoint — redelivery redoes both the ffmpeg step and
the OpenAI call from scratch, an accepted trade-off for this MVP's state
machine (true exactly-once cost control would need finer-grained
checkpointing than "one durable artifact per stage boundary", e.g.
persisting partial ffmpeg output too — not worth the complexity here). The
best-effort `failed` transition re-reads the episode's current status from
DynamoDB rather than trusting a status variable captured before the
exception — every transition is durably committed *before* the next stage's
riskier work begins, so a fresh read is always accurate regardless of where
exactly an exception was raised, and is simpler than threading a mutable
"last known status" through every helper. Two SSM parameters instead of one
shared "LLM key", for the reason above. Kept `PythonFunction`/zip for
`ApiFunction` unchanged — only the worker needs ffmpeg, so only the worker
needs the container-image switch; splitting packaging strategy per-Lambda by
actual need, not uniformly.

### Sabotage exercise findings (factual account — for the Learned line above)

Run against the real docker-compose + LocalStack stack (not a simulation),
with `AI_STUB=1` (so no real LLM was ever involved) and the new
`WORKER_SABOTAGE_INVALID_METADATA=1` toggle set on the `worker` service
(`docker compose up -d --force-recreate worker`), then a real episode
uploaded through the real API with a real (ffmpeg-generated silent) mp3.

The worker ran the full chain for real up through `generating`: downloaded
the upload, ffmpeg-transcoded it, wrote a (stubbed) transcript to S3,
transitioned to `generating`, then called `generate_metadata()` — which,
with the sabotage flag on, validates a payload containing
`{"label": "Broken Resource", "url": "not-a-url"}` against the real
`EpisodeMetadata`/`Resource` Pydantic model instead of a real LLM response.
Pydantic rejected it immediately:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for EpisodeMetadata
resources.0.url
  Input should be a valid URL, relative URL without a base [type=url_parsing, input_value='not-a-url', input_type=str]
```

The exception propagated up through `_advance_generating` → `_run_pipeline`
→ `_process_s3_record`'s `except Exception` handler, which re-read the
episode's current status (`generating`), fired the conditional
`generating → failed` transition, and re-raised. The handler reported the
SQS message as a batch item failure; the episode's final DynamoDB state was
`status=failed` with `title`/`description`/`resources` left empty — no
malformed URL, no partial garbage, ever reached a persisted field. With the
queue's real `maxReceiveCount=3`, the same message would be retried twice
more (same deterministic validation failure each time) before landing in
the DLQ, exactly as Phase 4's exercise #1 already proved for a different
kind of forced failure.

**Trade-off discussion — retry-with-feedback vs. fail-to-DLQ:** fail-to-DLQ
(what's implemented) is "free" — it's the exact same mechanism Phase 4
already built for any other worker failure, requires no new code, and
guarantees a human eventually sees *why* an episode got stuck (the DLQ's
whole purpose). Its cost is that a genuinely bad LLM response burns a full
transcription's worth of API cost (already spent, transcription happens
before generation) and produces zero forward progress — the episode just
sits in the DLQ until a human intervenes, even though the failure might be
trivially fixable by asking the model to try again. Retry-with-feedback (not
implemented) — catching the `ValidationError`, re-invoking the chain with
the error message appended to the prompt ("your last response had this
validation error, fix it and try again") — would recover automatically from
a large class of LLM mistakes (a model that's 95% right and just formatted
one field wrong) without ever reaching the DLQ, at the cost of: a second LLM
call's worth of money and latency per retry, a bound needed on how many
times to retry before giving up anyway (or it just becomes a slower path to
the same DLQ), and meaningfully more code (the chain needs to accept
"previous attempt + error" as input, not just the transcript). For this
MVP, at this volume, fail-to-DLQ is the right default: a bad metadata
generation is rare enough that a human re-triggering the pipeline
(re-uploading, or a future "retry" admin action) costs less than building
and maintaining a bounded-retry-with-feedback loop. Revisit
retry-with-feedback if malformed structured output turns out to be common
enough in practice that a human is spending real time babysitting the DLQ
for it.

### Cost

**Transcription** (OpenAI `gpt-4o-mini-transcribe`): ≈$0.003/minute of
audio, i.e. **≈$0.18 for a full hour-long episode** — the CLAUDE.md-mandated
number, unchanged from the plan. `gpt-4o-transcribe` (the higher-quality
sibling) is roughly 2x that, a straightforward upgrade path
(`worker/transcription.py::TRANSCRIBE_MODEL`) if transcript quality ever
becomes the bottleneck. **Metadata generation** (LangChain +
`gpt-4o-mini`): a full transcript is roughly 4,000-6,000 tokens for a
25-minute episode, plus a short prompt and a small structured JSON response
— on the order of a few thousand input tokens and a few hundred output
tokens per episode, which at `gpt-4o-mini`'s per-token pricing is a small
fraction of a cent per episode — negligible next to the transcription cost,
but worth naming explicitly. **Neither of these numbers was spent this
session** — `AI_STUB=1` was on for every local run, every automated test,
and the sabotage exercise; this task never held or used a real OpenAI/
Anthropic key. Both figures matter only once Igor sets the real SSM
parameter values and flips a deployed worker's `AI_STUB` to `0`.

**Open questions:** none.

**Next step:** start Phase 6 — Frontend (AI-built), per manual.md. Broad
shape: a Next.js static-export admin view (upload form hitting
`POST /api/v1/episodes` + the presigned S3 POST, an admin-key-gated review
queue for episodes sitting in `status=review` — the human-in-the-loop step
this pipeline has been building toward, letting a person approve/edit the
AI-generated title/description/resources before publish) and a public
streaming page listing `status=published` episodes (a status this project
hasn't introduced yet — Phase 6 likely adds `EpisodeStatus.PUBLISHED` and
the API action that sets it, alongside the frontend that triggers it).
Deployed via GitHub Pages per the Session-3-era decision recorded above
Session 5. Read manual.md's own Phase 6 section for the authoritative scope
before starting.

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
