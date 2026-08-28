"""Integration tests for the Phase 6 public read routes:
`GET /api/v1/episodes` (list) and `GET /api/v1/episodes/{id}` (detail).

Run via: docker compose run --rm api uv run pytest tests/integration

Episodes are seeded directly into DynamoDB (bypassing the upload/worker
pipeline entirely) — these tests are about the read routes' filtering,
pagination, and 404 behavior, not about how an episode gets to a given
status. test_processing_flow.py already proves the real pipeline lands an
episode at `review`; test_episodes_admin_review_flow.py proves
`review -> published`.
"""

from datetime import UTC, datetime
from uuid import uuid4


def _seed_episode(
    dynamodb_table,
    *,
    status: str,
    audio_key: str | None = None,
    duration: int = 60,
    created_at: str | None = None,
    title: str | None = None,
    description: str | None = None,
) -> str:
    episode_id = str(uuid4())
    now = created_at or datetime.now(UTC).isoformat()
    dynamodb_table.put_item(
        Item={
            "PK": f"EPISODE#{episode_id}",
            "SK": f"EPISODE#{episode_id}",
            "GSI1PK": "EPISODE",
            "GSI1SK": f"{now}#{episode_id}",
            "id": episode_id,
            "title": title or f"Episode {episode_id[:8]}",
            "description": description or "A seeded test episode.",
            "status": status,
            "duration": duration,
            "release_date": now,
            "audio_url": None,
            "audio_key": audio_key or f"uploads/{episode_id}.mp3",
            "image_url": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    return episode_id


def test_get_episodes_only_returns_published(http_client, dynamodb_table):
    published_id = _seed_episode(dynamodb_table, status="published")
    review_id = _seed_episode(dynamodb_table, status="review")

    response = http_client.get("/api/v1/episodes", params={"limit": 50})
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}

    assert published_id in ids
    assert review_id not in ids


def test_get_episodes_response_includes_presigned_audio_url(
    http_client, dynamodb_table
):
    published_id = _seed_episode(dynamodb_table, status="published")

    response = http_client.get("/api/v1/episodes", params={"limit": 50})
    items = {item["id"]: item for item in response.json()["items"]}

    assert published_id in items
    audio_url = items[published_id]["audio_url"]
    assert audio_url is not None
    assert audio_url.startswith("http")


def test_get_episodes_pagination_cursor_reaches_every_published_episode(
    http_client, dynamodb_table
):
    """Walk the cursor with a deliberately tiny page size and confirm every
    seeded published episode eventually turns up, and the walk terminates
    (cursor=None) — the bounded loop is a safety net against an infinite-
    pagination regression, not an expectation of many iterations."""
    seeded_ids = {_seed_episode(dynamodb_table, status="published") for _ in range(3)}

    seen_ids: set[str] = set()
    cursor = None
    for _ in range(500):
        params = {"limit": 1}
        if cursor:
            params["cursor"] = cursor
        response = http_client.get("/api/v1/episodes", params=params)
        assert response.status_code == 200
        body = response.json()
        seen_ids.update(item["id"] for item in body["items"])
        cursor = body["cursor"]
        if cursor is None:
            break
    else:
        raise AssertionError("cursor never became None — pagination isn't terminating")
    assert seeded_ids.issubset(seen_ids)


def test_get_episodes_supports_oldest_sort(http_client, dynamodb_table):
    newer_id = _seed_episode(
        dynamodb_table, status="published", created_at="2026-01-02T00:00:00+00:00"
    )
    older_id = _seed_episode(
        dynamodb_table, status="published", created_at="2026-01-01T00:00:00+00:00"
    )

    response = http_client.get(
        "/api/v1/episodes", params={"limit": 50, "sort": "oldest"}
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids.index(older_id) < ids.index(newer_id)


def test_get_episodes_supports_longest_sort_and_pagination(http_client, dynamodb_table):
    short_id = _seed_episode(dynamodb_table, status="published", duration=30)
    long_id = _seed_episode(dynamodb_table, status="published", duration=300)

    response = http_client.get(
        "/api/v1/episodes", params={"limit": 1, "sort": "longest"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["id"] == long_id
    assert body["cursor"] is not None

    items = [body["items"][0]["id"]]
    cursor = body["cursor"]
    while cursor:
        response = http_client.get(
            "/api/v1/episodes",
            params={"limit": 1, "sort": "longest", "cursor": cursor},
        )
        assert response.status_code == 200
        items.extend(item["id"] for item in response.json()["items"])
        cursor = response.json()["cursor"]
    assert items.index(long_id) < items.index(short_id)


def test_get_episodes_q_matches_title_substring(http_client, dynamodb_table):
    matching_id = _seed_episode(
        dynamodb_table, status="published", title="A Chat About Rockets"
    )
    other_id = _seed_episode(dynamodb_table, status="published", title="Cooking Basics")

    response = http_client.get(
        "/api/v1/episodes", params={"limit": 50, "q": "Rockets"}
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert matching_id in ids
    assert other_id not in ids


def test_get_episodes_q_matches_description_substring(http_client, dynamodb_table):
    matching_id = _seed_episode(
        dynamodb_table,
        status="published",
        title="Episode One",
        description="This one talks about space travel.",
    )
    other_id = _seed_episode(
        dynamodb_table,
        status="published",
        title="Episode Two",
        description="This one talks about baking bread.",
    )

    response = http_client.get(
        "/api/v1/episodes", params={"limit": 50, "q": "space travel"}
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert matching_id in ids
    assert other_id not in ids


def test_get_episodes_q_is_case_insensitive(http_client, dynamodb_table):
    matching_id = _seed_episode(
        dynamodb_table, status="published", title="A Chat About Rockets"
    )

    response = http_client.get(
        "/api/v1/episodes", params={"limit": 50, "q": "rOcKeTs"}
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert matching_id in ids


def test_get_episodes_q_combined_with_longest_sort(http_client, dynamodb_table):
    matching_short_id = _seed_episode(
        dynamodb_table, status="published", title="Rockets Short", duration=30
    )
    matching_long_id = _seed_episode(
        dynamodb_table, status="published", title="Rockets Long", duration=300
    )
    non_matching_id = _seed_episode(
        dynamodb_table, status="published", title="Cooking Long", duration=500
    )

    response = http_client.get(
        "/api/v1/episodes",
        params={"limit": 50, "sort": "longest", "q": "Rockets"},
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert non_matching_id not in ids
    assert ids.index(matching_long_id) < ids.index(matching_short_id)


def test_get_episodes_q_pagination_reaches_every_match(http_client, dynamodb_table):
    """Same bounded-loop shape as the plain pagination test above, but with
    `q` set and a non-matching episode seeded alongside — proves the
    Python-side offset cursor terminates and never leaks the non-match."""
    matching_ids = {
        _seed_episode(dynamodb_table, status="published", title=f"Rockets {i}")
        for i in range(3)
    }
    non_matching_id = _seed_episode(dynamodb_table, status="published", title="Cooking")

    seen_ids: set[str] = set()
    cursor = None
    for _ in range(500):
        params = {"limit": 1, "q": "Rockets"}
        if cursor:
            params["cursor"] = cursor
        response = http_client.get("/api/v1/episodes", params=params)
        assert response.status_code == 200
        body = response.json()
        seen_ids.update(item["id"] for item in body["items"])
        cursor = body["cursor"]
        if cursor is None:
            break
    else:
        raise AssertionError("cursor never became None — pagination isn't terminating")
    assert matching_ids.issubset(seen_ids)
    assert non_matching_id not in seen_ids


def test_get_episode_detail_returns_published_episode(http_client, dynamodb_table):
    published_id = _seed_episode(dynamodb_table, status="published")

    response = http_client.get(f"/api/v1/episodes/{published_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == published_id
    assert body["status"] == "published"
    assert body["audio_url"].startswith("http")


def test_get_episode_detail_404s_for_unpublished_episode(http_client, dynamodb_table):
    review_id = _seed_episode(dynamodb_table, status="review")

    response = http_client.get(f"/api/v1/episodes/{review_id}")
    assert response.status_code == 404


def test_get_episode_detail_404s_for_missing_episode(http_client):
    response = http_client.get(f"/api/v1/episodes/{uuid4()}")
    assert response.status_code == 404
