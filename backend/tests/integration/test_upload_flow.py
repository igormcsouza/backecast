"""Integration tests for POST /api/v1/episodes (Phase 3 upload flow).

Run via: docker compose run --rm api uv run pytest tests/integration
"""

import os


def test_create_episode_returns_presigned_post_and_uploading_item(
    http_client, admin_headers, dynamodb_table
):
    response = http_client.post(
        "/api/v1/episodes",
        headers=admin_headers,
        json={"filename": "ep.mp3", "content_type": "audio/mpeg"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "uploading"
    assert body["upload"]["url"]
    assert "key" in body["upload"]["fields"]

    episode_id = body["id"]
    item = dynamodb_table.get_item(
        Key={"PK": f"EPISODE#{episode_id}", "SK": f"EPISODE#{episode_id}"}
    )["Item"]
    assert item["status"] == "uploading"
    assert item["audio_key"] == f"uploads/{episode_id}.mp3"


def test_presigned_post_actually_uploads_to_s3(http_client, admin_headers, s3_client):
    create_response = http_client.post(
        "/api/v1/episodes",
        headers=admin_headers,
        json={"filename": "ep.mp3", "content_type": "audio/mpeg"},
    )
    upload = create_response.json()["upload"]

    upload_response = http_client.post(
        upload["url"],
        data=upload["fields"],
        files={"file": ("ep.mp3", b"fake-audio-bytes", "audio/mpeg")},
    )
    assert upload_response.status_code in (200, 204)

    # bucket name isn't part of the presigned fields; read it from the env
    key = upload["fields"]["key"]
    bucket_name = os.environ.get("MEDIA_BUCKET_NAME", "backecast-media-dev")
    head = s3_client.head_object(Bucket=bucket_name, Key=key)
    assert head["ContentLength"] == len(b"fake-audio-bytes")


def test_create_episode_without_admin_key_is_rejected(http_client):
    response = http_client.post(
        "/api/v1/episodes",
        json={"filename": "ep.mp3", "content_type": "audio/mpeg"},
    )
    assert response.status_code == 401


def test_create_episode_with_wrong_admin_token_is_rejected(http_client):
    response = http_client.post(
        "/api/v1/episodes",
        headers={"Authorization": "Bearer wrong-token"},
        json={"filename": "ep.mp3", "content_type": "audio/mpeg"},
    )
    assert response.status_code == 401
