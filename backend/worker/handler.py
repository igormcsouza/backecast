"""SQS-triggered worker Lambda: preprocess -> transcribe -> generate metadata.

S3 (ObjectCreated on `uploads/`) -> SQS queue -> this handler. Phase 4 proved
the wiring with a two-step stub (`uploading -> processing -> processed-stub`).
Phase 5 replaces that stub middle with the real pipeline, entirely inside one
worker invocation (no async job orchestration / Step Functions): ffmpeg
preprocessing (worker/audio.py), OpenAI transcription (worker/transcription.py),
a LangChain metadata chain (worker/metadata.py), then a DynamoDB write. The
state machine grows from two transitions to five:

    uploading -> processing -> transcribing -> generating -> review
                      -> rejected (duration over the cap, straight from
                          processing -- no transcription attempt, no cost)

Any unrecoverable error at any stage moves the episode to `failed` and
re-raises, so the caller reports the SQS message as failed and Phase 4's
existing retry/DLQ mechanics take over unchanged (see MAX_RECEIVE_COUNT in
infra/stacks/pipeline_stack.py) -- this handler never swallows an exception
to "protect" the episode from ending up in the DLQ; a human being able to
see *why* a specific episode kept failing is the point of the DLQ existing.

Written as a plain synchronous handler on purpose, same as Phase 4 -- this
is the idiomatic shape for an SQS-triggered Lambda (AWS invokes it directly,
one batch per invocation; there's no ASGI event loop to protect here the way
there is in the API Lambda), and it keeps this module free of the "no
blocking boto3 inside `async def`" rule entirely rather than relying on
discipline to avoid breaking it. It's also why the ffmpeg subprocess calls,
the OpenAI SDK call, and the LangChain chain invocation below are all fine
to call directly and let block -- there's no event loop here to stall.

Concepts this module demonstrates (see manual.md Phase 5 for the full
teaching notes; Phase 4's docstring, still accurate for the mechanisms
below, covered at-least-once delivery / conditional-write idempotency /
partial batch failures):

- **Coarse-grained resumable state machine**: each `if status == X:` branch
  re-derives everything the from durable storage (S3) it needs to do that
  stage's work, rather than depending on any Python object surviving from a
  previous, crashed invocation -- a fresh Lambda container has an empty
  /tmp and no memory of what a prior attempt got partway through. The one
  exception, deliberately: the full transcript is written to S3 *before*
  the `transcribing -> generating` transition, so a crash between those two
  stages resumes by re-reading the already-paid-for transcript from S3
  instead of re-paying OpenAI to transcribe the same audio again. A crash
  *during* transcription itself has no such checkpoint -- redelivery redoes
  the ffmpeg step and the transcription call from scratch. That's an
  accepted trade-off for this MVP's simple state machine: real exactly-once
  cost control would need finer-grained checkpointing than "one durable
  artifact per stage boundary."
- **ffmpeg + a container image, not a zip**: see worker/audio.py's
  docstring for why the audio preprocessing step exists, and
  worker/Dockerfile / infra/stacks/pipeline_stack.py for why that forces
  this Lambda to be a container image.
- **Transcript in S3, not DynamoDB**: DynamoDB caps a single item at 400KB;
  a real episode's transcript can exceed that. S3 has no such limit, and
  this pipeline already has a bucket (the same media bucket the raw upload
  lives in, under a `transcripts/` prefix instead of `uploads/`).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.episodes.schemas import EpisodeStatus
from worker import audio
from worker.metadata import generate_metadata
from worker.transcription import transcribe_audio

logger = get_logger("worker")
settings = get_settings()

TABLE_NAME = os.environ.get("TABLE_NAME", "backecast-dev")
AWS_REGION = os.environ.get("AWS_REGION", "sa-east-1")
AWS_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL") or None

MAX_EPISODE_DURATION_SECONDS = settings.max_episode_duration_seconds
TRANSCRIPT_KEY_PREFIX = settings.transcript_key_prefix

# --- Sabotage hooks (Phase 4 mandatory exercises, still wired the same way) -
# Both default to off (no-ops in normal operation, including in production —
# the env vars are simply never set there). They exist so the sabotage
# exercises can be run against the *real* worker code and the *real* local
# stack instead of a throwaway script, then switched back off. See
# SESSIONS.md for what was observed running each of these.
#
# 1) WORKER_SABOTAGE_FORCE_FAILURE=1 — raise before doing any work, so every
#    message in the batch fails every time. Used to watch SQS retry a
#    message up to `maxReceiveCount` and then move it to the DLQ.
# 2) WORKER_SABOTAGE_SLEEP_SECONDS=N — sleep for N seconds *after* the first
#    idempotent transition, simulating slow processing. Combined with a
#    queue visibility timeout set lower than N, this reproduces duplicate
#    delivery.
# 3) WORKER_SABOTAGE_INVALID_METADATA=1 — Phase 5's new exercise, defined in
#    worker/metadata.py (imported there, not re-declared here) — makes the
#    AI_STUB metadata payload malformed so Pydantic validation fails.
SABOTAGE_FORCE_FAILURE = os.environ.get("WORKER_SABOTAGE_FORCE_FAILURE") == "1"
SABOTAGE_SLEEP_SECONDS = float(
    os.environ.get("WORKER_SABOTAGE_SLEEP_SECONDS", "0") or 0
)

# Clients initialized at module level (Lambda best practice): a cold start
# pays the connection-setup cost once, warm invocations reuse it.
_dynamodb = boto3.resource(
    "dynamodb",
    region_name=AWS_REGION,
    endpoint_url=AWS_ENDPOINT_URL,
    config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
)
_table = _dynamodb.Table(TABLE_NAME)

# A separate, more generous timeout than the DynamoDB client: this one
# downloads whole audio files (megabytes, not a single item's worth of
# bytes) and uploads a full transcript, so 5s would be far too tight.
_s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    endpoint_url=AWS_ENDPOINT_URL,
    config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 1}),
)


def _episode_id_from_key(key: str) -> str | None:
    """`uploads/{episode_id}.mp3` -> `{episode_id}`."""
    filename = key.rsplit("/", 1)[-1]
    episode_id = filename.rsplit(".", 1)[0]
    return episode_id or None


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _transition(
    episode_id: str,
    from_status: EpisodeStatus,
    to_status: EpisodeStatus,
    extra_attributes: dict | None = None,
) -> bool:
    """Conditionally move an episode from one status to the next.

    Returns True if the transition actually happened, False if the
    condition failed (item already past this point — a duplicate delivery
    or an out-of-order/unexpected message, either way safe to skip).
    Any other DynamoDB error re-raises so the caller reports the message as
    failed and lets SQS retry it.

    `extra_attributes`, new in Phase 5: lets a transition also persist
    additional fields in the *same* conditional write — used by the
    generating -> review transition to write title/description/resources
    atomically with the status change, so a redelivery can never observe
    "status=review but metadata still empty" (or vice versa). Attribute
    names are passed through DynamoDB expression-attribute-name placeholders
    (`#a0`, `#a1`, ...) rather than interpolated directly, the same
    reservation-safe pattern `#status` uses below — several of this item's
    field names (e.g. a hypothetical future field) could otherwise collide
    with a DynamoDB reserved word.
    """
    set_clauses = ["#status = :to", "updated_at = :now"]
    names = {"#status": "status"}
    values = {
        ":to": to_status.value,
        ":from": from_status.value,
        ":now": _now(),
    }
    for i, (attr, value) in enumerate(sorted((extra_attributes or {}).items())):
        name_placeholder, value_placeholder = f"#a{i}", f":v{i}"
        set_clauses.append(f"{name_placeholder} = {value_placeholder}")
        names[name_placeholder] = attr
        values[value_placeholder] = value

    try:
        _table.update_item(
            Key={"PK": f"EPISODE#{episode_id}", "SK": f"EPISODE#{episode_id}"},
            UpdateExpression="SET " + ", ".join(set_clauses),
            ConditionExpression="#status = :from",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info(
                "transition skipped (idempotency guard)",
                extra={
                    "episode_id": episode_id,
                    "from": from_status.value,
                    "to": to_status.value,
                },
            )
            return False
        raise
    return True


def _current_status(episode_id: str) -> str | None:
    """Consistent read of the episode's status, or None if the item doesn't exist."""
    resp = _table.get_item(
        Key={"PK": f"EPISODE#{episode_id}", "SK": f"EPISODE#{episode_id}"},
        ProjectionExpression="#status",
        ExpressionAttributeNames={"#status": "status"},
        ConsistentRead=True,
    )
    item = resp.get("Item")
    return item["status"] if item else None


def _transcript_key(episode_id: str) -> str:
    return f"{TRANSCRIPT_KEY_PREFIX}{episode_id}.json"


def _download_audio(bucket: str, key: str, episode_id: str) -> str:
    suffix = Path(key).suffix or ".mp3"
    local_path = os.path.join(tempfile.gettempdir(), f"{episode_id}-raw{suffix}")
    _s3.download_file(bucket, key, local_path)
    return local_path


def _preprocess_audio(bucket: str, key: str, episode_id: str) -> str:
    """Download the raw upload and ffmpeg-preprocess it. Returns the local
    path of the compressed, transcription-ready file.

    Raises audio.EpisodeTooLongError (via audio.preprocess's duration check,
    run before any transcoding) if the source exceeds
    MAX_EPISODE_DURATION_SECONDS — the caller turns that into a `rejected`
    transition, not a `failed` one; being too long is an expected, handled
    outcome, not a worker error.
    """
    raw_path = _download_audio(bucket, key, episode_id)
    compressed_path = os.path.join(
        tempfile.gettempdir(), f"{episode_id}-compressed.m4a"
    )
    try:
        audio.preprocess(raw_path, compressed_path, MAX_EPISODE_DURATION_SECONDS)
    finally:
        audio.cleanup(raw_path)
    return compressed_path


def _write_transcript(bucket: str, episode_id: str, transcript: dict) -> None:
    _s3.put_object(
        Bucket=bucket,
        Key=_transcript_key(episode_id),
        Body=json.dumps(transcript).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )


def _read_transcript_text(bucket: str, episode_id: str) -> str:
    """Plain text only — the LangChain metadata chain (worker/metadata.py)
    wants prose, not the structured segment/word timestamps."""
    response = _s3.get_object(Bucket=bucket, Key=_transcript_key(episode_id))
    transcript = json.loads(response["Body"].read().decode("utf-8"))
    return transcript["text"]


def _mark_failed_best_effort(episode_id: str) -> None:
    """On any unhandled exception, try to leave the episode in `failed`
    rather than silently stuck in whatever in-flight status it was in.

    Re-reads the current status rather than trusting a status variable
    captured before the exception: every transition in this module is
    durably committed to DynamoDB *before* the next stage's (riskier) work
    begins, so a fresh read always reflects the last stage that actually
    completed, regardless of exactly where the exception was raised.

    "Best-effort": the conditional transition only fires if that status is
    one of the in-flight statuses this worker owns. If it's already past
    that (e.g. a concurrent delivery already advanced the item further, or
    already marked it failed), the conditional write simply no-ops — same
    idempotency guard as every other transition in this module.
    """
    current = _current_status(episode_id)
    in_flight = (
        EpisodeStatus.PROCESSING,
        EpisodeStatus.TRANSCRIBING,
        EpisodeStatus.GENERATING,
    )
    for candidate in in_flight:
        if candidate.value == current:
            _transition(episode_id, candidate, EpisodeStatus.FAILED)
            return


def _advance_uploading(episode_id: str) -> str:
    moved = _transition(episode_id, EpisodeStatus.UPLOADING, EpisodeStatus.PROCESSING)
    return EpisodeStatus.PROCESSING.value if moved else _current_status(episode_id)


def _advance_processing(
    bucket: str, key: str, episode_id: str
) -> tuple[str | None, str | None]:
    """Do the `processing` stage's work. Returns (next_status, compressed_path).

    `next_status` is None if the episode was rejected for exceeding the
    duration cap — the caller must stop there (not treat it as a failure).
    """
    if SABOTAGE_SLEEP_SECONDS > 0:
        logger.warning(
            "sabotage: sleeping to simulate slow processing",
            extra={"episode_id": episode_id, "seconds": SABOTAGE_SLEEP_SECONDS},
        )
        time.sleep(SABOTAGE_SLEEP_SECONDS)

    try:
        compressed_path = _preprocess_audio(bucket, key, episode_id)
    except audio.EpisodeTooLongError as e:
        # Straight to `rejected`, not `failed` — this is an expected,
        # handled outcome (no transcription attempt, no OpenAI cost), not a
        # worker error. The caller returns without raising, so the SQS
        # message is treated as successfully processed.
        _transition(episode_id, EpisodeStatus.PROCESSING, EpisodeStatus.REJECTED)
        logger.warning(
            "episode rejected: duration exceeds cap",
            extra={
                "episode_id": episode_id,
                "duration_seconds": e.duration_seconds,
                "cap_seconds": e.cap_seconds,
            },
        )
        return None, None

    moved = _transition(
        episode_id, EpisodeStatus.PROCESSING, EpisodeStatus.TRANSCRIBING
    )
    if not moved:
        # Lost a race with a concurrent delivery of the same message — it
        # already advanced the item past `processing`. Our locally
        # transcoded file is now orphaned (the winner will redo the
        # transcode itself when it gets here, since no local file survives
        # across invocations/containers anyway), so clean it up now rather
        # than leaking it in /tmp across warm-container reuse.
        audio.cleanup(compressed_path)
        return _current_status(episode_id), None
    return EpisodeStatus.TRANSCRIBING.value, compressed_path


def _advance_transcribing(
    bucket: str, key: str, episode_id: str, compressed_path: str | None
) -> str:
    if compressed_path is None:
        # Resumed directly into `transcribing` in a fresh invocation — no
        # local file survives across invocations (or across Lambda
        # containers), so redo the ffmpeg step. Duration was already
        # checked once to get this far, but audio.preprocess() re-checks it
        # anyway (cheap, and the source hasn't changed) rather than adding
        # a second code path that skips it. Same handled-outcome guard as
        # _advance_processing: if the cap changed between deploys (or this
        # is the race-loser path from _advance_processing, which now always
        # resumes here with compressed_path=None), a duration-cap failure
        # on the redo must still land on `rejected`, not `failed` — the
        # episode shouldn't get a different terminal status just because it
        # happened to be caught the second time instead of the first.
        try:
            compressed_path = _preprocess_audio(bucket, key, episode_id)
        except audio.EpisodeTooLongError as e:
            _transition(episode_id, EpisodeStatus.TRANSCRIBING, EpisodeStatus.REJECTED)
            logger.warning(
                "episode rejected: duration exceeds cap",
                extra={
                    "episode_id": episode_id,
                    "duration_seconds": e.duration_seconds,
                    "cap_seconds": e.cap_seconds,
                },
            )
            return EpisodeStatus.REJECTED.value

    try:
        transcript = transcribe_audio(compressed_path)
    finally:
        audio.cleanup(compressed_path)

    _write_transcript(bucket, episode_id, transcript)
    moved = _transition(
        episode_id, EpisodeStatus.TRANSCRIBING, EpisodeStatus.GENERATING
    )
    return EpisodeStatus.GENERATING.value if moved else _current_status(episode_id)


def _advance_generating(bucket: str, episode_id: str) -> None:
    # Always re-read from S3 rather than threading a variable through from
    # the stage above: this is the resumability checkpoint described in the
    # module docstring — a crash after the transcribing -> generating
    # transition redelivers here with no in-memory transcript, but the S3
    # object is already durably written, so this stage's redo cost is just
    # the LLM call, not another OpenAI transcription charge.
    transcript_text = _read_transcript_text(bucket, episode_id)
    episode_metadata = generate_metadata(transcript_text)
    _transition(
        episode_id,
        EpisodeStatus.GENERATING,
        EpisodeStatus.REVIEW,
        extra_attributes={
            "title": episode_metadata.title,
            "description": episode_metadata.description,
            "resources": [
                r.model_dump(mode="json") for r in episode_metadata.resources
            ],
        },
    )


def _run_pipeline(bucket: str, key: str, episode_id: str, status: str) -> None:
    """Walk the state machine forward from `status`, doing each stage's real
    work as it goes — one or many stages per call, depending on how far a
    single invocation gets before returning (a redelivered message resumes
    wherever the *item* is, not wherever this particular call started).
    """
    compressed_path = None

    if status == EpisodeStatus.UPLOADING.value:
        status = _advance_uploading(episode_id)

    if status == EpisodeStatus.PROCESSING.value:
        status, compressed_path = _advance_processing(bucket, key, episode_id)
        if status is None:
            return  # rejected — see _advance_processing

    if status == EpisodeStatus.TRANSCRIBING.value:
        status = _advance_transcribing(bucket, key, episode_id, compressed_path)

    if status == EpisodeStatus.GENERATING.value:
        _advance_generating(bucket, episode_id)
        logger.info("processing complete", extra={"episode_id": episode_id})
        return

    # Anything else (already `review`/`rejected`/`failed`, or a status this
    # worker doesn't own) — a duplicate delivery of a fully-completed
    # message. Safe no-op.
    logger.info(
        "transition skipped (idempotency guard)",
        extra={"episode_id": episode_id, "status": status},
    )


def _process_s3_record(s3_record: dict) -> None:
    bucket = s3_record["s3"]["bucket"]["name"]
    key = unquote_plus(s3_record["s3"]["object"]["key"])
    episode_id = _episode_id_from_key(key)
    if not episode_id:
        logger.warning("could not derive episode id from key", extra={"key": key})
        return

    logger.info(
        "processing started",
        extra={"episode_id": episode_id, "bucket": bucket, "key": key},
    )

    if SABOTAGE_FORCE_FAILURE:
        raise RuntimeError(
            "sabotage: WORKER_SABOTAGE_FORCE_FAILURE=1 — simulating a worker crash "
            "to observe SQS retry -> DLQ behavior"
        )

    # Redelivery can land here at any point in the state machine — not just
    # before the first transition. Look at where the item actually is and
    # resume from there, instead of assuming redelivery always means
    # "start of the day zero" (Phase 4's lesson, still true, now generalized
    # to a five-state chain instead of two).
    status = _current_status(episode_id)
    if status is None:
        logger.warning("episode item not found", extra={"episode_id": episode_id})
        return

    try:
        _run_pipeline(bucket, key, episode_id, status)
    except Exception:
        _mark_failed_best_effort(episode_id)
        raise


def _process_message_body(body: str) -> None:
    payload = json.loads(body)

    # LocalStack (and real S3) sends a one-off `s3:TestEvent` the moment a
    # bucket notification is first configured, before any real uploads
    # happen — it has no `s3` key and must be ignored, not treated as a
    # processing failure.
    if payload.get("Event") == "s3:TestEvent":
        logger.info("skipping s3:TestEvent")
        return

    for s3_record in payload.get("Records", []):
        _process_s3_record(s3_record)


def handler(event: dict, context=None) -> dict:
    """SQS batch handler.

    `event["Records"]` is the batch of SQS messages (batch size configured
    on the event source mapping in CDK). Each message's `body` is the raw
    S3 event notification JSON since S3 -> SQS is wired directly, no SNS
    fan-out in between.
    """
    failures: list[dict] = []
    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            _process_message_body(record["body"])
        except Exception:
            logger.exception(
                "failed to process message, will be retried",
                extra={"message_id": message_id},
            )
            failures.append({"itemIdentifier": message_id})

    # Empty list = every message in the batch succeeded, delete them all.
    # A partial list tells SQS (via ReportBatchItemFailures) to redeliver
    # only those specific messages and delete the rest.
    return {"batchItemFailures": failures}
