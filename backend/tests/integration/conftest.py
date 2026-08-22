"""Fixtures for integration tests against the docker-compose/LocalStack stack.

These tests run inside the compose network (`docker compose run --rm api uv
run pytest tests/integration`), not from the bare host: the API signs
presigned S3 URLs against AWS_ENDPOINT_URL (http://localstack:4566), which
only resolves inside that network. Running from the host would produce a
presigned URL nobody outside the compose network can reach.
"""

import os

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
