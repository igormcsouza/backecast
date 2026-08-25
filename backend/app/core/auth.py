"""Cognito-backed admin auth: verifies a Bearer access token against the
admin User Pool's public JWKS (`infra/stacks/auth_stack.py`) on every
admin request.

`AUTH_STUB=1` (settings.auth_stub, same shape as AI_STUB elsewhere in this
app): skip real Cognito verification and accept one well-known bearer
token instead. Only ever set locally and in CI — LocalStack Community
doesn't include Cognito, so there's nothing real to verify against there;
see docker-compose.yml and backend/tests/integration/conftest.py.

The JWKS response is cached at module scope after the first fetch, the
same warm-container-reuse pattern the old admin-key SSM lookup used (and
DynamoDB's client in shared/dynamodb.py) — it's a fixed, rarely-rotated
public key set, not worth re-fetching every request.
"""

import asyncio

import httpx
import jwt
from fastapi import Depends, Header

from app.core.exceptions import AdminAuthError
from app.core.settings import Settings, get_settings

# Not a real secret — only ever compared against when AUTH_STUB=1, which is
# never set for a real (dev/prod) deploy. See module docstring.
LOCAL_STUB_TOKEN = "local-dev-admin-token"  # noqa: S105

_cached_jwks: dict | None = None
_lock = asyncio.Lock()


async def _get_jwks(settings: Settings) -> dict:
    global _cached_jwks
    if _cached_jwks is None:
        async with _lock:
            if _cached_jwks is None:  # re-check after acquiring the lock
                url = (
                    f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
                    f"{settings.cognito_user_pool_id}/.well-known/jwks.json"
                )
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    _cached_jwks = response.json()
    return _cached_jwks


def _find_signing_key(jwks: dict, kid: str) -> jwt.PyJWK:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return jwt.PyJWK.from_dict(key)
    raise AdminAuthError()


async def require_admin_key(
    authorization: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> None:
    if authorization is None or not authorization.startswith("Bearer "):
        raise AdminAuthError()
    token = authorization.removeprefix("Bearer ")

    if settings.auth_stub:
        if token != LOCAL_STUB_TOKEN:
            raise AdminAuthError()
        return

    try:
        unverified_header = jwt.get_unverified_header(token)
        jwks = await _get_jwks(settings)
        signing_key = _find_signing_key(jwks, unverified_header["kid"])
        claims = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=["RS256"],
            issuer=(
                f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
                f"{settings.cognito_user_pool_id}"
            ),
            # Cognito access tokens carry `client_id`, not `aud` (that's an
            # ID-token-only claim) — verified manually below instead of via
            # PyJWT's built-in `audience=` check.
            options={"require": ["exp", "iss", "client_id", "token_use"]},
        )
    except (jwt.InvalidTokenError, AdminAuthError, KeyError):
        raise AdminAuthError() from None

    if claims.get("token_use") != "access" or claims.get("client_id") != settings.cognito_client_id:
        raise AdminAuthError()
