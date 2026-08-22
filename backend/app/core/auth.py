"""X-Admin-Key auth dependency.

The admin secret lives in SSM Parameter Store, never in env vars or git.
Fetching it from SSM on every request would add latency and an extra paid
API call per invocation, so the resolved value is cached at module scope
after the first fetch — the same warm-container-reuse pattern the DynamoDB
resource in shared/dynamodb.py uses. The cache lives for the Lambda
container's lifetime; rotating the secret only takes effect on the next
cold start (acceptable for a single shared admin key with no rotation SLA).
"""

import asyncio
import secrets

from fastapi import Depends, Header

from app.core.exceptions import AdminAuthError
from app.core.settings import Settings, get_settings
from app.shared.dynamodb import CLIENT_CONFIG, session

_cached_admin_key: str | None = None
_lock = asyncio.Lock()


async def _get_admin_key(settings: Settings) -> str:
    global _cached_admin_key
    if _cached_admin_key is None:
        async with _lock:
            if _cached_admin_key is None:  # re-check after acquiring the lock
                async with session.client(
                    "ssm",
                    region_name=settings.aws_region,
                    endpoint_url=settings.aws_endpoint_url,
                    config=CLIENT_CONFIG,
                ) as ssm:
                    response = await ssm.get_parameter(
                        Name=settings.admin_key_param_name, WithDecryption=True
                    )
                    _cached_admin_key = response["Parameter"]["Value"]
    return _cached_admin_key


async def require_admin_key(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = await _get_admin_key(settings)
    if x_admin_key is None or not secrets.compare_digest(x_admin_key, expected):
        raise AdminAuthError()
