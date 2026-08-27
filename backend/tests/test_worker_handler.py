"""Unit tests for worker/handler.py — no AWS, no Docker, no ffmpeg.

The real DynamoDB table (worker._table) is monkeypatched with a tiny
in-memory fake that understands enough of the conditional UpdateItem
contract (including Phase 5's extra_attributes SET clauses) to exercise the
idempotency guard and the partial-batch-failure reporting.

The ffmpeg preprocessing step (`_preprocess_audio`) and the S3 transcript
read/write helpers are monkeypatched too — this file tests the *state
machine*, not ffmpeg or S3, both of which the docker-compose integration
test (backend/tests/integration/test_processing_flow.py) exercises for
real. Transcription and metadata generation are deliberately left
un-mocked: AI_STUB=1 (set globally in conftest.py) already makes
worker.transcription.transcribe_audio() and worker.metadata.generate_metadata()
return canned values without any network call, so exercising them for real
here means these tests cover the *actual* Pydantic-validation and
DynamoDB-write code paths, not a re-implementation of them.
"""

import json

import pytest
from botocore.exceptions import ClientError

from worker import audio as worker_audio
from worker import handler as worker_handler
from worker import metadata as worker_metadata


class FakeTable:
    """In-memory stand-in for the DynamoDB Table resource.

    Understands a conditional `update_item` (raises
    ConditionalCheckFailedException when the item's current status doesn't
    match the expected `:from` value) and applies every clause of the SET
    expression generically — not just `#status`/`updated_at` — so it stays
    correct as `_transition()`'s `extra_attributes` grows the expression.
    """

    def __init__(self, items: dict[str, dict]) -> None:
        self.items = items

    def update_item(
        self,
        *,
        Key,
        UpdateExpression,
        ConditionExpression,
        ExpressionAttributeNames,
        ExpressionAttributeValues,
    ):
        pk = Key["PK"]
        item = self.items.setdefault(pk, {})
        expected_from = ExpressionAttributeValues[":from"]
        current = item.get("status")
        if current != expected_from:
            raise ClientError(
                {
                    "Error": {
                        "Code": "ConditionalCheckFailedException",
                        "Message": "condition failed",
                    }
                },
                "UpdateItem",
            )

        set_expression = UpdateExpression.removeprefix("SET ")
        for clause in set_expression.split(", "):
            name_token, value_token = (part.strip() for part in clause.split("="))
            attr_name = ExpressionAttributeNames.get(name_token, name_token)
            item[attr_name] = ExpressionAttributeValues[value_token]

    def get_item(
        self,
        *,
        Key,
        ProjectionExpression,
        ExpressionAttributeNames,
        ConsistentRead=True,
    ):
        pk = Key["PK"]
        item = self.items.get(pk)
        if item is None:
            return {}
        return {"Item": {"status": item["status"]}}


@pytest.fixture(autouse=True)
def reset_sabotage_flags(monkeypatch):
    """Every test starts from the non-sabotage default, regardless of env."""
    monkeypatch.setattr(worker_handler, "SABOTAGE_FORCE_FAILURE", False)
    monkeypatch.setattr(worker_handler, "SABOTAGE_SLEEP_SECONDS", 0)
    monkeypatch.setattr(worker_metadata, "SABOTAGE_INVALID_METADATA", False)


@pytest.fixture
def fake_table(monkeypatch):
    table = FakeTable(items={})
    monkeypatch.setattr(worker_handler, "_table", table)
    return table


@pytest.fixture(autouse=True)
def stub_ffmpeg_and_s3(monkeypatch):
    """Replace the ffmpeg/S3 boundary with fakes; leave the AI_STUB=1
    transcription/metadata code paths and Pydantic validation real."""
    monkeypatch.setattr(
        worker_handler,
        "_preprocess_audio",
        lambda bucket, key, episode_id: ("/tmp/fake-compressed.m4a", 754.3),
    )
    monkeypatch.setattr(
        worker_handler, "_write_transcript", lambda bucket, episode_id, text: None
    )
    monkeypatch.setattr(
        worker_handler,
        "_read_transcript_text",
        lambda bucket, episode_id: "fake transcript text",
    )


def _s3_event_body(bucket: str, key: str) -> str:
    return json.dumps(
        {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}
    )


def _sqs_record(message_id: str, body: str) -> dict:
    return {"messageId": message_id, "body": body}


def test_transitions_uploading_to_review(fake_table):
    episode_id = "abc123"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "uploading"}

    event = {
        "Records": [
            _sqs_record("m1", _s3_event_body("bucket", f"uploads/{episode_id}.mp3"))
        ]
    }
    result = worker_handler.handler(event)

    assert result == {"batchItemFailures": []}
    item = fake_table.items[f"EPISODE#{episode_id}"]
    assert item["status"] == "review"
    # The AI_STUB metadata payload (worker/metadata.py) went through real
    # Pydantic validation and landed in the DynamoDB item.
    assert item["title"] == "Stubbed Episode Title"
    assert item["resources"] == [
        {"label": "Example Resource", "url": "https://example.com/resource"}
    ]
    # Written during processing->transcribing (see _advance_processing) from
    # ffprobe's source-file duration, rounded to the nearest second.
    assert item["duration"] == 754


def test_duplicate_delivery_is_a_safe_no_op(fake_table):
    """Idempotency guard: processing the same message twice must not corrupt state."""
    episode_id = "dup1"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "uploading"}
    body = _s3_event_body("bucket", f"uploads/{episode_id}.mp3")

    first = worker_handler.handler({"Records": [_sqs_record("m1", body)]})
    assert first == {"batchItemFailures": []}
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "review"

    second = worker_handler.handler({"Records": [_sqs_record("m2", body)]})
    assert second == {"batchItemFailures": []}
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "review"


def test_forced_failure_reports_message_as_batch_item_failure(fake_table, monkeypatch):
    monkeypatch.setattr(worker_handler, "SABOTAGE_FORCE_FAILURE", True)
    episode_id = "fail1"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "uploading"}

    event = {
        "Records": [
            _sqs_record("m1", _s3_event_body("bucket", f"uploads/{episode_id}.mp3"))
        ]
    }
    result = worker_handler.handler(event)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    # Never even got to the first transition.
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "uploading"


def test_partial_batch_failure_only_reports_the_failing_message(
    fake_table, monkeypatch
):
    """One bad message in a batch must not cause the whole batch to retry."""
    good_id, bad_id = "good1", "bad1"
    fake_table.items[f"EPISODE#{good_id}"] = {"status": "uploading"}
    fake_table.items[f"EPISODE#{bad_id}"] = {"status": "uploading"}

    good_body = _s3_event_body("bucket", f"uploads/{good_id}.mp3")
    bad_body = "not-json"  # can never be processed, independent of sabotage flags

    event = {
        "Records": [
            _sqs_record("m-good", good_body),
            _sqs_record("m-bad", bad_body),
        ]
    }
    result = worker_handler.handler(event)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m-bad"}]}
    assert fake_table.items[f"EPISODE#{good_id}"]["status"] == "review"
    assert fake_table.items[f"EPISODE#{bad_id}"]["status"] == "uploading"


def test_resumes_from_processing_after_crash_between_transitions(fake_table):
    """A prior delivery crashed after uploading->processing but before the
    rest of the chain completed. Redelivery must resume from `processing`.
    """
    episode_id = "resume1"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "processing"}
    body = _s3_event_body("bucket", f"uploads/{episode_id}.mp3")

    result = worker_handler.handler({"Records": [_sqs_record("m1", body)]})

    assert result == {"batchItemFailures": []}
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "review"


def test_resumes_from_transcribing_by_redoing_ffmpeg(fake_table, monkeypatch):
    """A prior delivery crashed mid-transcription (after processing->
    transcribing but before a transcript was written). No local file
    survives a fresh invocation, so `_preprocess_audio` must be called
    again — this test proves it's actually invoked, not skipped.
    """
    episode_id = "resume2"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "transcribing"}
    body = _s3_event_body("bucket", f"uploads/{episode_id}.mp3")

    calls = []
    monkeypatch.setattr(
        worker_handler,
        "_preprocess_audio",
        lambda bucket, key, eid: calls.append(eid) or ("/tmp/fake-compressed.m4a", 300.0),
    )

    result = worker_handler.handler({"Records": [_sqs_record("m1", body)]})

    assert result == {"batchItemFailures": []}
    assert calls == [episode_id]
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "review"


def test_resumes_from_generating_by_rereading_transcript_from_s3(
    fake_table, monkeypatch
):
    """A prior delivery crashed after transcribing->generating but before
    the LLM call finished. Redelivery must re-read the already-durably-
    stored transcript from S3, not require any in-memory carryover.
    """
    episode_id = "resume3"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "generating"}
    body = _s3_event_body("bucket", f"uploads/{episode_id}.mp3")

    read_calls = []
    monkeypatch.setattr(
        worker_handler,
        "_read_transcript_text",
        lambda bucket, eid: read_calls.append(eid) or "fake transcript text",
    )

    result = worker_handler.handler({"Records": [_sqs_record("m1", body)]})

    assert result == {"batchItemFailures": []}
    assert read_calls == [episode_id]
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "review"


def test_episode_rejected_when_duration_exceeds_cap(fake_table, monkeypatch):
    """ffmpeg's duration probe finds the upload over the transcription cap:
    status must go straight to `rejected`, no failure reported (this is an
    expected, handled outcome, not a worker error — no transcription
    attempt was made, so no cost was incurred).
    """
    episode_id = "toolong1"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "uploading"}
    body = _s3_event_body("bucket", f"uploads/{episode_id}.mp3")

    def _raise_too_long(bucket, key, eid):
        raise worker_audio.EpisodeTooLongError(duration_seconds=2000, cap_seconds=1500)

    monkeypatch.setattr(worker_handler, "_preprocess_audio", _raise_too_long)

    result = worker_handler.handler({"Records": [_sqs_record("m1", body)]})

    assert result == {"batchItemFailures": []}
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "rejected"


def test_failure_during_metadata_generation_marks_failed_and_reports_for_retry(
    fake_table, monkeypatch
):
    episode_id = "boom1"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "generating"}
    body = _s3_event_body("bucket", f"uploads/{episode_id}.mp3")

    def _raise(transcript):
        raise RuntimeError("simulated LLM/provider outage")

    monkeypatch.setattr(worker_handler, "generate_metadata", _raise)

    result = worker_handler.handler({"Records": [_sqs_record("m1", body)]})

    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "failed"


def test_sabotage_invalid_metadata_shape_fails_pydantic_validation(
    fake_table, monkeypatch
):
    """Phase 5 mandatory sabotage exercise, automated: force the AI_STUB
    metadata payload into a malformed shape (bad resource URL) and confirm
    Pydantic rejects it, the episode ends up `failed` (not silently
    `review` with garbage data), and the message is reported for retry ->
    eventual DLQ, same as any other failure in this stage.
    """
    monkeypatch.setattr(worker_metadata, "SABOTAGE_INVALID_METADATA", True)
    episode_id = "sabotage1"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "generating"}
    body = _s3_event_body("bucket", f"uploads/{episode_id}.mp3")

    result = worker_handler.handler({"Records": [_sqs_record("m1", body)]})

    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "failed"


def test_s3_test_event_is_ignored(fake_table):
    """S3/LocalStack sends a one-off s3:TestEvent when notifications are first
    configured — it must not be treated as a processing failure."""
    body = json.dumps({"Service": "Amazon S3", "Event": "s3:TestEvent"})
    result = worker_handler.handler({"Records": [_sqs_record("m1", body)]})
    assert result == {"batchItemFailures": []}
