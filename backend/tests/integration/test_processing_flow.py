"""Integration test for the Phase 5 pipeline: upload -> review.

Run via: docker compose up -d  (starts localstack + init + api + worker)
         docker compose run --rm api uv run pytest tests/integration

Must run inside the compose network for the same reason as
test_upload_flow.py: the presigned POST is signed against
http://localstack:4566, unreachable from the bare host.

AI_STUB=1 is set on the worker service in docker-compose.yml, so this test
proves the *real* pipeline end to end — real ffmpeg preprocessing, real S3
transcript write, real Pydantic validation of the metadata, real DynamoDB
write — with only the actual network call to OpenAI/the LLM provider
swapped out. See SESSIONS.md for the real-world cost this pipeline would
incur with AI_STUB=0 against real infra.
"""

import time

import pytest

POLL_TIMEOUT_SECONDS = 60
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


def test_upload_triggers_pipeline_and_reaches_review_with_ai_metadata(
    http_client, admin_headers, dynamodb_table, s3_client, tiny_audio_bytes
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
        files={"file": ("ep.mp3", tiny_audio_bytes, "audio/mpeg")},
    )
    assert upload_response.status_code in (200, 204)

    # The S3 PUT above is what triggers the S3 -> SQS -> worker chain. By the
    # time this reaches `review`, the worker has run the *entire* Phase 5
    # chain: uploading -> processing (ffmpeg) -> transcribing (OpenAI, AI_STUB)
    # -> generating (LangChain, AI_STUB) -> review, each an idempotent
    # conditional transition.
    item = _poll_until_status(dynamodb_table, episode_id, "review")
    assert item["status"] == "review"

    # AI-generated (stubbed, but real-Pydantic-validated) metadata landed in
    # DynamoDB — this is the Definition of Done from manual.md Phase 5.
    assert item["title"] == "Stubbed Episode Title"
    assert item["description"]
    assert item["resources"] == [
        {"label": "Example Resource", "url": "https://example.com/resource"}
    ]

    # The transcript itself lives in S3, not DynamoDB (see worker/handler.py's
    # docstring for why) — confirm it's really there.
    transcript = s3_client.get_object(
        Bucket="backecast-media-dev", Key=f"transcripts/{episode_id}.txt"
    )
    transcript_text = transcript["Body"].read().decode("utf-8")
    assert "stubbed transcript" in transcript_text.lower()


# The `rejected` (over duration cap) path is intentionally not covered here:
# reproducing it black-box would mean uploading 25+ real minutes of audio
# through this same slow, polling integration test. It's covered directly at
# the unit level instead — see
# test_worker_handler.py::test_episode_rejected_when_duration_exceeds_cap,
# which exercises the exact same `processing -> rejected` transition by
# monkeypatching the duration check rather than generating a real long file.
