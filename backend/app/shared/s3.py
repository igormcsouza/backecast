"""Presigned POST helper for direct-to-S3 audio uploads.

Presigned POST (not PUT) is used deliberately: a POST policy document can
carry `Conditions` — `content-length-range` and an exact `Content-Type` —
that S3 itself enforces at upload time, before any of our code runs. A
presigned PUT URL has no such conditions; anything of any size could be
pushed to it.

`generate_presigned_post` is a synchronous boto3 call (aioboto3 doesn't wrap
S3 presigning — it's local crypto/URL construction, not network I/O, but it's
still a blocking call under the hood). Per the project's async-discipline
rule, it must not run inline inside an `async def` route, so it's dispatched
through `run_in_threadpool`.
"""

import boto3
from botocore.config import Config
from starlette.concurrency import run_in_threadpool

from app.core.settings import get_settings

settings = get_settings()

_s3_client = boto3.client(
    "s3",
    region_name=settings.aws_region,
    # This client only ever presigns URLs (see the module docstring) — never
    # makes a live call to S3 itself — so it's safe for it to use a
    # different, browser-reachable endpoint than the one api/worker use for
    # their own direct AWS calls. See Settings.aws_endpoint_url_public.
    endpoint_url=settings.aws_endpoint_url_public or settings.aws_endpoint_url,
    config=Config(s3={"addressing_style": "path"}),
)


def _build_presigned_post(
    bucket: str, key: str, content_type: str, max_bytes: int
) -> dict:
    return _s3_client.generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, max_bytes],
        ],
        ExpiresIn=900,
    )


async def create_presigned_post(
    bucket: str, key: str, content_type: str, max_bytes: int
) -> dict:
    return await run_in_threadpool(
        _build_presigned_post, bucket, key, content_type, max_bytes
    )


def _build_presigned_get(bucket: str, key: str, expires_in: int) -> str:
    return _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


async def create_presigned_get(bucket: str, key: str, expires_in: int = 3600) -> str:
    """Presigned GET for streaming an episode's audio (Phase 6).

    Chosen over standing up a CloudFront distribution in front of the media
    bucket: no new billable resource, reuses this module's existing
    presigning pattern (now for GET instead of POST), and a presigned S3 URL
    already serves byte-range requests — the thing that actually makes
    HTML5 `<audio>` seeking work — with no extra configuration. The
    trade-off (documented in SESSIONS.md) is that the URL expires
    (`expires_in`, default 1h) and isn't cached at the edge, both fine for
    this MVP's traffic. Same `run_in_threadpool` treatment as
    `create_presigned_post`: local crypto/URL construction, not network
    I/O, but still a blocking boto3 call that must not run inline inside an
    `async def`.
    """
    return await run_in_threadpool(_build_presigned_get, bucket, key, expires_in)
