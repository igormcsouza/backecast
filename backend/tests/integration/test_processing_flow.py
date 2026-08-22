"""Integration test for the Phase 4 event pipeline (S3 -> SQS -> worker).

Run via: docker compose up -d  (starts localstack + init + api + worker)
         docker compose run --rm api uv run pytest tests/integration

Must run inside the compose network for the same reason as
test_upload_flow.py: the presigned POST is signed against
http://localstack:4566, unreachable from the bare host.
"""

import time

import pytest

POLL_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 1


def _poll_until_status(
    dynamodb_table,
    episode_id: str,
    target_status: str,
    timeout: float = POLL_TIMEOUT_SECONDS,
):
    """Poll the DynamoDB item until it reaches target_status, or fail after `timeout`.

    Why polling-with-timeout and not a plain assert right after upload: the
    pipeline from here on is entirely asynchronous (S3 event -> SQS ->
    worker Lambda/poller -> DynamoDB update) — the test has no synchronous
    signal telling it "processing just finished". A fixed `time.sleep()`
    would be flaky (too short under load, wastefully long otherwise) and an
    unbounded wait would hang forever on a genuine regression. Polling with
    a bounded deadline is the standard way to assert on an async pipeline's
    eventual outcome without either failure mode.
    """
    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        item = dynamodb_table.get_item(
            Key={"PK": f"EPISODE#{episode_id}", "SK": f"EPISODE#{episode_id}"}
        )["Item"]
        last_status = item["status"]
        if last_status == target_status:
            return item
        time.sleep(POLL_INTERVAL_SECONDS)
    pytest.fail(
        f"episode {episode_id} did not reach status={target_status!r} within "
        f"{timeout}s (last seen: {last_status!r})"
    )


def test_upload_triggers_pipeline_and_reaches_processed_stub(
    http_client, admin_headers, dynamodb_table
):
    create_response = http_client.post(
        "/api/v1/episodes",
        headers=admin_headers,
        json={"filename": "ep.mp3", "content_type": "audio/mpeg"},
    )
    assert create_response.status_code == 201
    body = create_response.json()
    episode_id = body["id"]
    assert body["status"] == "uploading"

    upload = body["upload"]
    upload_response = http_client.post(
        upload["url"],
        data=upload["fields"],
        files={"file": ("ep.mp3", b"fake-audio-bytes", "audio/mpeg")},
    )
    assert upload_response.status_code in (200, 204)

    # The S3 PUT above is what triggers the S3 -> SQS -> worker chain; by
    # the time the poller below sees processed-stub, the worker has already
    # applied both idempotent transitions (uploading -> processing ->
    # processed-stub).
    item = _poll_until_status(dynamodb_table, episode_id, "processed-stub")
    assert item["status"] == "processed-stub"
