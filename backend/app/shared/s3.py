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
    endpoint_url=settings.aws_endpoint_url,
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
