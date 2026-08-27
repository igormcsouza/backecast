"""Integration tests for the Phase 6 admin review/edit/publish routes:
`GET /api/v1/episodes/admin`, `GET /api/v1/episodes/{id}/admin`,
`PATCH /api/v1/episodes/{id}`, `POST /api/v1/episodes/{id}/publish`.

Run via: docker compose run --rm api uv run pytest tests/integration

Episodes are seeded directly into DynamoDB, same rationale as
test_public_episodes_flow.py — these tests are about the admin routes'
auth gate, status filtering, and status-transition guards, not about the
AI pipeline that normally produces a `review` episode.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx


def _seed_episode(dynamodb_table, *, status: str) -> str:
    episode_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    dynamodb_table.put_item(
        Item={
            "PK": f"EPISODE#{episode_id}",
            "SK": f"EPISODE#{episode_id}",
            "GSI1PK": "EPISODE",
            "GSI1SK": f"{now}#{episode_id}",
            "id": episode_id,
            "title": "Original Title",
            "description": "Original description.",
            "status": status,
            "duration": 60,
            "release_date": now,
            "audio_url": None,
            "audio_key": f"uploads/{episode_id}.mp3",
            "image_url": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    return episode_id


def test_admin_list_requires_admin_key(http_client):
    response = http_client.get("/api/v1/episodes/admin")
    assert response.status_code == 401


def test_admin_list_filters_by_status(http_client, admin_headers, dynamodb_table):
    review_id = _seed_episode(dynamodb_table, status="review")
    uploading_id = _seed_episode(dynamodb_table, status="uploading")

    response = http_client.get(
        "/api/v1/episodes/admin", params={"status": "review"}, headers=admin_headers
    )
    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body}

    assert review_id in ids
    assert uploading_id not in ids
    assert all(item["status"] == "review" for item in body)


def test_admin_get_episode_works_for_any_status(
    http_client, admin_headers, dynamodb_table
):
    uploading_id = _seed_episode(dynamodb_table, status="uploading")

    response = http_client.get(
        f"/api/v1/episodes/{uploading_id}/admin", headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "uploading"


def test_admin_get_episode_requires_admin_key(http_client, dynamodb_table):
    episode_id = _seed_episode(dynamodb_table, status="uploading")

    response = http_client.get(f"/api/v1/episodes/{episode_id}/admin")
    assert response.status_code == 401


def test_patch_episode_updates_metadata_when_in_review(
    http_client, admin_headers, dynamodb_table
):
    episode_id = _seed_episode(dynamodb_table, status="review")

    response = http_client.patch(
        f"/api/v1/episodes/{episode_id}",
        headers=admin_headers,
        json={
            "title": "Edited Title",
            "description": "Edited description.",
            "resources": [{"label": "Docs", "url": "https://example.com/docs"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Edited Title"
    assert body["description"] == "Edited description."

    item = dynamodb_table.get_item(
        Key={"PK": f"EPISODE#{episode_id}", "SK": f"EPISODE#{episode_id}"}
    )["Item"]
    assert item["title"] == "Edited Title"
    assert item["resources"] == [{"label": "Docs", "url": "https://example.com/docs"}]


def test_patch_episode_partial_update_only_touches_given_fields(
    http_client, admin_headers, dynamodb_table
):
    episode_id = _seed_episode(dynamodb_table, status="review")

    response = http_client.patch(
        f"/api/v1/episodes/{episode_id}",
        headers=admin_headers,
        json={"title": "Only Title Changed"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Only Title Changed"
    assert body["description"] == "Original description."


def test_patch_episode_rejected_when_not_in_review(
    http_client, admin_headers, dynamodb_table
):
    episode_id = _seed_episode(dynamodb_table, status="uploading")

    response = http_client.patch(
        f"/api/v1/episodes/{episode_id}",
        headers=admin_headers,
        json={"title": "Should Not Apply"},
    )
    assert response.status_code == 409


def test_patch_episode_requires_admin_key(http_client, dynamodb_table):
    episode_id = _seed_episode(dynamodb_table, status="review")

    response = http_client.patch(
        f"/api/v1/episodes/{episode_id}", json={"title": "No Auth"}
    )
    assert response.status_code == 401


def test_publish_episode_transitions_review_to_published(
    http_client, admin_headers, dynamodb_table
):
    episode_id = _seed_episode(dynamodb_table, status="review")

    response = http_client.post(
        f"/api/v1/episodes/{episode_id}/publish", headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "published"

    # And it's now visible on the public route, which it wasn't before.
    public_response = http_client.get(f"/api/v1/episodes/{episode_id}")
    assert public_response.status_code == 200


def test_publish_episode_rejected_when_not_in_review(
    http_client, admin_headers, dynamodb_table
):
    episode_id = _seed_episode(dynamodb_table, status="uploading")

    response = http_client.post(
        f"/api/v1/episodes/{episode_id}/publish", headers=admin_headers
    )
    assert response.status_code == 409


def test_publish_episode_requires_admin_key(http_client, dynamodb_table):
    episode_id = _seed_episode(dynamodb_table, status="review")

    response = http_client.post(f"/api/v1/episodes/{episode_id}/publish")
    assert response.status_code == 401


def test_publish_episode_404s_for_missing_episode(http_client, admin_headers):
    response = http_client.post(
        f"/api/v1/episodes/{uuid4()}/publish", headers=admin_headers
    )
    assert response.status_code == 404


def _seed_transcript(s3_client, episode_id: str, text: str = "stubbed transcript text"):
    body = json.dumps(
        {
            "text": text,
            "segments": [{"text": text, "start": 0.0, "end": 1.0, "words": []}],
        }
    )
    s3_client.put_object(
        Bucket="backecast-media-dev",
        Key=f"transcripts/{episode_id}.json",
        Body=body.encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )


def test_admin_get_transcript_returns_presigned_url_for_any_status(
    http_client, admin_headers, dynamodb_table, s3_client
):
    episode_id = _seed_episode(dynamodb_table, status="review")
    _seed_transcript(s3_client, episode_id)

    response = http_client.get(
        f"/api/v1/episodes/{episode_id}/transcript/admin", headers=admin_headers
    )
    assert response.status_code == 200
    url = response.json()["url"]

    fetched = httpx.get(url)
    assert fetched.status_code == 200
    assert fetched.json()["text"] == "stubbed transcript text"


def test_admin_get_transcript_requires_admin_key(http_client, dynamodb_table):
    episode_id = _seed_episode(dynamodb_table, status="review")

    response = http_client.get(f"/api/v1/episodes/{episode_id}/transcript/admin")
    assert response.status_code == 401


def test_admin_get_transcript_404s_for_missing_episode(http_client, admin_headers):
    response = http_client.get(
        f"/api/v1/episodes/{uuid4()}/transcript/admin", headers=admin_headers
    )
    assert response.status_code == 404


def test_public_get_transcript_returns_presigned_url_for_published_episode(
    http_client, dynamodb_table, s3_client
):
    episode_id = _seed_episode(dynamodb_table, status="published")
    _seed_transcript(s3_client, episode_id)

    response = http_client.get(f"/api/v1/episodes/{episode_id}/transcript")
    assert response.status_code == 200
    url = response.json()["url"]

    fetched = httpx.get(url)
    assert fetched.status_code == 200
    assert fetched.json()["text"] == "stubbed transcript text"


def test_public_get_transcript_404s_for_unpublished_episode(
    http_client, dynamodb_table, s3_client
):
    episode_id = _seed_episode(dynamodb_table, status="review")
    _seed_transcript(s3_client, episode_id)

    response = http_client.get(f"/api/v1/episodes/{episode_id}/transcript")
    assert response.status_code == 404


def test_public_get_transcript_404s_for_missing_episode(http_client):
    response = http_client.get(f"/api/v1/episodes/{uuid4()}/transcript")
    assert response.status_code == 404
