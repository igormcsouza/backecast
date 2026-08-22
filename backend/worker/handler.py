"""SQS-triggered worker Lambda: the Phase 4 event pipeline consumer.

S3 (ObjectCreated on `uploads/`) -> SQS queue -> this handler. No AI yet —
the worker only proves the wiring by flipping an episode's status
`uploading -> processing -> processed-stub`. Phase 5 replaces the middle of
this function with real transcription + LangChain metadata generation; the
state-machine shape (idempotent transition, then work, then idempotent
transition) stays the same.

Written as a plain synchronous handler on purpose — this is the idiomatic
shape for an SQS-triggered Lambda (AWS invokes it directly, one batch per
invocation; there's no ASGI event loop to protect here the way there is in
the API Lambda), and it keeps this module free of the "no blocking boto3
inside `async def`" rule entirely rather than relying on discipline to
avoid breaking it.

Concepts this module demonstrates (see manual.md Phase 4 for the full
teaching notes):

- **At-least-once delivery**: SQS guarantees a message is delivered at
  least once, never exactly once. A message can be redelivered because the
  consumer crashed, timed out, or (see visibility timeout below) simply
  didn't finish before its lease expired — even though the first delivery
  actually succeeded. Code downstream of SQS must assume "this might be the
  second (or fifth) time I'm seeing this event."
- **Idempotency via conditional writes** (`_transition`): every status
  change is a DynamoDB `UpdateItem` conditioned on the *current* status
  being the expected "from" state. A redelivered message finds the item
  already past that state, the condition fails, and the transition is
  silently skipped — same effect as if the message had only ever been
  processed once. This is the same primitive `EpisodesRepository.create()`
  uses (`attribute_not_exists(PK)`), reused here for a status transition
  instead of a fresh row.
- **Partial batch failures** (`handler`): a batch can contain several
  messages; if one raises and the others succeed, returning every message
  ID as failed would cause SQS to redeliver messages that already
  succeeded — wasted work at best, corrupted-looking retries at worst
  (though idempotency defends against real corruption). Reporting only the
  IDs that actually failed (`ReportBatchItemFailures`, enabled on the SQS
  event source mapping in CDK) tells SQS to redeliver only those specific
  messages and delete the rest of the batch normally.
"""

from __future__ import annotations

import json
import os
import time
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.logging import get_logger
from app.episodes.schemas import EpisodeStatus

logger = get_logger("worker")

TABLE_NAME = os.environ.get("TABLE_NAME", "backecast-dev")
AWS_REGION = os.environ.get("AWS_REGION", "sa-east-1")
AWS_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL") or None

# --- Sabotage hooks (Phase 4 mandatory exercises) ---------------------------
# Both default to off (no-ops in normal operation, including in production —
# the env vars are simply never set there). They exist so the three sabotage
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
#    delivery: a second worker picks up the same message before the first
#    one finishes and is proven safe (or not) by whether the idempotency
#    guard is in place.
SABOTAGE_FORCE_FAILURE = os.environ.get("WORKER_SABOTAGE_FORCE_FAILURE") == "1"
SABOTAGE_SLEEP_SECONDS = float(
    os.environ.get("WORKER_SABOTAGE_SLEEP_SECONDS", "0") or 0
)

# Client initialized at module level (Lambda best practice): a cold start
# pays the connection-setup cost once, warm invocations reuse it.
_dynamodb = boto3.resource(
    "dynamodb",
    region_name=AWS_REGION,
    endpoint_url=AWS_ENDPOINT_URL,
    config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
)
_table = _dynamodb.Table(TABLE_NAME)


def _episode_id_from_key(key: str) -> str | None:
    """`uploads/{episode_id}.mp3` -> `{episode_id}`."""
    filename = key.rsplit("/", 1)[-1]
    episode_id = filename.rsplit(".", 1)[0]
    return episode_id or None


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _transition(
    episode_id: str, from_status: EpisodeStatus, to_status: EpisodeStatus
) -> bool:
    """Conditionally move an episode from one status to the next.

    Returns True if the transition actually happened, False if the
    condition failed (item already past this point — a duplicate delivery
    or an out-of-order/unexpected message, either way safe to skip).
    Any other DynamoDB error re-raises so the caller reports the message as
    failed and lets SQS retry it.
    """
    try:
        _table.update_item(
            Key={"PK": f"EPISODE#{episode_id}", "SK": f"EPISODE#{episode_id}"},
            UpdateExpression="SET #status = :to, updated_at = :now",
            ConditionExpression="#status = :from",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":to": to_status.value,
                ":from": from_status.value,
                ":now": _now(),
            },
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

    moved = _transition(episode_id, EpisodeStatus.UPLOADING, EpisodeStatus.PROCESSING)
    if not moved:
        # Either a duplicate delivery of a message already processed, or the
        # item is in some other state entirely — nothing further to do.
        # This is the idempotency guard exercised directly by sabotage #2
        # (duplicate delivery under a too-short visibility timeout) and
        # sabotage #3 (the same file uploaded/processed twice).
        return

    if SABOTAGE_SLEEP_SECONDS > 0:
        logger.warning(
            "sabotage: sleeping to simulate slow processing",
            extra={"episode_id": episode_id, "seconds": SABOTAGE_SLEEP_SECONDS},
        )
        time.sleep(SABOTAGE_SLEEP_SECONDS)

    _transition(episode_id, EpisodeStatus.PROCESSING, EpisodeStatus.PROCESSED_STUB)
    logger.info("processing complete", extra={"episode_id": episode_id})


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
