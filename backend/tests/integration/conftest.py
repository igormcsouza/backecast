"""Fixtures for integration tests against the docker-compose/LocalStack stack.

These tests run inside the compose network (`docker compose run --rm api uv
run pytest tests/integration`), not from the bare host: the API signs
presigned S3 URLs against AWS_ENDPOINT_URL (http://localstack:4566), which
only resolves inside that network. Running from the host would produce a
presigned URL nobody outside the compose network can reach.
"""

import os
import subprocess

import boto3
import httpx
import pytest

API_BASE_URL = os.environ.get("INTEGRATION_API_URL", "http://api:8000")
LOCALSTACK_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localstack:4566")
ADMIN_KEY = "local-dev-admin-key"
TABLE_NAME = os.environ.get("TABLE_NAME", "backecast-dev")
MEDIA_BUCKET_NAME = os.environ.get("MEDIA_BUCKET_NAME", "backecast-media-dev")


@pytest.fixture
def http_client():
    with httpx.Client(base_url=API_BASE_URL, timeout=10) as client:
        yield client


@pytest.fixture
def admin_headers():
    return {"X-Admin-Key": ADMIN_KEY}


@pytest.fixture
def dynamodb_table():
    resource = boto3.resource(
        "dynamodb", region_name="sa-east-1", endpoint_url=LOCALSTACK_ENDPOINT
    )
    return resource.Table(TABLE_NAME)


@pytest.fixture
def s3_client():
    return boto3.client("s3", region_name="sa-east-1", endpoint_url=LOCALSTACK_ENDPOINT)


@pytest.fixture
def tiny_audio_bytes() -> bytes:
    """A real (tiny, ~1s, silent) mp3 — Phase 5's worker runs it through
    real ffprobe/ffmpeg (worker/audio.py), so `b"fake-audio-bytes"` (good
    enough for Phase 4's stub, which never opened the file) won't do: ffprobe
    would fail to read a duration from it and the episode would end up
    `failed`, not `review`. Generated at test time via ffmpeg's `lavfi`
    silence source rather than committing a binary fixture to the repo — the
    `api` container this test runs in has ffmpeg installed for exactly this
    reason (see backend/Dockerfile).
    """
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-t",
            "1",
            "-q:a",
            "9",
            "-f",
            "mp3",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return result.stdout
