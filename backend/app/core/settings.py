"""Settings module for the application.

This module defines the Settings class, which is a subclass of
BaseSettings from the Pydantic library. The Settings class is used
to manage application configuration settings, such as the stage
(e.g., development, production) of the application.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    version: str = "0.1.0"
    stage: str = "dev"
    table_name: str = "backecast-dev"
    aws_region: str = "sa-east-1"
    aws_endpoint_url: str | None = None  # set thru env vars
    # Only ever needed locally: `aws_endpoint_url` is the docker-compose
    # network hostname (`http://localstack:4566`) the api/worker containers
    # use to actually reach LocalStack — but a presigned URL bakes that same
    # host into the URL itself, and a browser running on the *host* machine
    # (not inside the compose network) can't resolve `localstack` at all.
    # Presigning is pure local crypto/URL construction (no network call at
    # signing time), so the presigning client can safely use a different,
    # host-reachable endpoint without affecting any other AWS call. Falls
    # back to `aws_endpoint_url` (real AWS in prod has no such split) unless
    # docker-compose.yml overrides it for local dev.
    aws_endpoint_url_public: str | None = None
    media_bucket_name: str = "backecast-media-dev"

    # --- Admin auth (Cognito) -----------------------------------------------
    # AUTH_STUB=1 (same pattern as AI_STUB below): skip real Cognito JWKS
    # verification entirely and accept a single well-known bearer token
    # instead. Only ever set locally/in CI — LocalStack Community doesn't
    # include Cognito, so there's nothing real to point this at there. See
    # app/core/auth.py.
    auth_stub: bool = False
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    cognito_region: str = "sa-east-1"

    max_upload_bytes: int = 60 * 1024 * 1024  # ~60MB: a 25-min mp3 + headroom
    allowed_content_types: tuple[str, ...] = ("audio/mpeg", "audio/mp4", "audio/x-m4a")

    # --- Phase 5: worker-side AI settings -----------------------------------
    # These are read by backend/worker/*.py, not by the FastAPI app — kept
    # here (rather than duplicated as bare os.environ reads like handler.py's
    # TABLE_NAME/AWS_REGION) because they're genuinely shared shape (a Pydantic
    # Settings object), and the worker Lambda gets its own environment block in
    # infra/stacks/pipeline_stack.py so unused fields here simply fall back to
    # their defaults there, same as ADMIN_KEY_PARAM_NAME does for the worker
    # today.
    ai_stub: bool = False  # AI_STUB=1: no real OpenAI/Anthropic network calls
    openai_api_key_param_name: str = "/backecast/dev/openai-api-key"
    # A "<provider>:<model>" string, exactly the shape langchain's
    # init_chat_model() accepts — swapping OpenAI for Anthropic is a one-line
    # env var change (LLM_MODEL=anthropic:claude-3-5-haiku-latest), not a
    # code change. The chat model's API key is resolved from SSM using
    # llm_api_key_param_name below and passed in explicitly, so this seam
    # works for either provider without extra branching.
    llm_model: str = "openai:gpt-4o-mini"
    llm_api_key_param_name: str = "/backecast/dev/llm-api-key"
    transcript_key_prefix: str = "transcripts/"
    # OpenAI's transcription endpoint caps input at 25MB / ~25 minutes;
    # ffmpeg preprocessing keeps the transcoded file well under the size
    # cap, so duration is the binding constraint worth checking explicitly.
    max_episode_duration_seconds: int = 25 * 60


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Caching the Settings instance (instead of a single attribute) ensures
    that subsequent calls reuse the same parsed configuration object.
    """
    return Settings()
