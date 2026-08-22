"""Unit tests for worker/handler.py — no AWS, no Docker.

The real DynamoDB table (worker._table) is monkeypatched with a tiny
in-memory fake that understands just enough of the conditional UpdateItem
contract to exercise the idempotency guard and the partial-batch-failure
reporting, without needing moto or LocalStack.
"""

import json

import pytest
from botocore.exceptions import ClientError

from worker import handler as worker_handler


class FakeTable:
    """In-memory stand-in for the DynamoDB Table resource.

    Only implements what `_transition` needs: a conditional update_item that
    raises ConditionalCheckFailedException when the item's current status
    doesn't match the expected `:from` value.
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
        item["status"] = ExpressionAttributeValues[":to"]
        item["updated_at"] = ExpressionAttributeValues[":now"]


@pytest.fixture(autouse=True)
def reset_sabotage_flags(monkeypatch):
    """Every test starts from the non-sabotage default, regardless of env."""
    monkeypatch.setattr(worker_handler, "SABOTAGE_FORCE_FAILURE", False)
    monkeypatch.setattr(worker_handler, "SABOTAGE_SLEEP_SECONDS", 0)


@pytest.fixture
def fake_table(monkeypatch):
    table = FakeTable(items={})
    monkeypatch.setattr(worker_handler, "_table", table)
    return table


def _s3_event_body(bucket: str, key: str) -> str:
    return json.dumps(
        {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}
    )


def _sqs_record(message_id: str, body: str) -> dict:
    return {"messageId": message_id, "body": body}


def test_transitions_uploading_to_processed_stub(fake_table):
    episode_id = "abc123"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "uploading"}

    event = {
        "Records": [
            _sqs_record("m1", _s3_event_body("bucket", f"uploads/{episode_id}.mp3"))
        ]
    }
    result = worker_handler.handler(event)

    assert result == {"batchItemFailures": []}
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "processed-stub"


def test_duplicate_delivery_is_a_safe_no_op(fake_table):
    """Idempotency guard: processing the same message twice must not corrupt state.

    This is the automated counterpart of sabotage exercise #3 (upload/process
    the same episode twice) and the "fixed" half of exercise #2 (duplicate
    delivery under a short visibility timeout) — the second delivery finds
    the item already past `uploading` and skips cleanly.
    """
    episode_id = "dup1"
    fake_table.items[f"EPISODE#{episode_id}"] = {"status": "uploading"}
    body = _s3_event_body("bucket", f"uploads/{episode_id}.mp3")

    first = worker_handler.handler({"Records": [_sqs_record("m1", body)]})
    assert first == {"batchItemFailures": []}
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "processed-stub"

    # Redelivery of an equivalent message — status is already processed-stub,
    # so the uploading->processing transition's condition fails and nothing
    # further happens. No exception, no corrupted state.
    second = worker_handler.handler({"Records": [_sqs_record("m2", body)]})
    assert second == {"batchItemFailures": []}
    assert fake_table.items[f"EPISODE#{episode_id}"]["status"] == "processed-stub"


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
    # Malformed body (invalid JSON) simulates a message that can never be
    # processed successfully, independent of the force-failure sabotage flag.
    bad_body = "not-json"

    event = {
        "Records": [
            _sqs_record("m-good", good_body),
            _sqs_record("m-bad", bad_body),
        ]
    }
    result = worker_handler.handler(event)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m-bad"}]}
    assert fake_table.items[f"EPISODE#{good_id}"]["status"] == "processed-stub"
    assert fake_table.items[f"EPISODE#{bad_id}"]["status"] == "uploading"


def test_s3_test_event_is_ignored(fake_table):
    """S3/LocalStack sends a one-off s3:TestEvent when notifications are first
    configured — it must not be treated as a processing failure."""
    body = json.dumps({"Service": "Amazon S3", "Event": "s3:TestEvent"})
    result = worker_handler.handler({"Records": [_sqs_record("m1", body)]})
    assert result == {"batchItemFailures": []}
