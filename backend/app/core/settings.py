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
    media_bucket_name: str = "backecast-media-dev"
    admin_key_param_name: str = "/backecast/dev/admin-key"
    max_upload_bytes: int = 60 * 1024 * 1024  # ~60MB: a 25-min mp3 + headroom
    allowed_content_types: tuple[str, ...] = ("audio/mpeg", "audio/mp4", "audio/x-m4a")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Caching the Settings instance (instead of a single attribute) ensures
    that subsequent calls reuse the same parsed configuration object.
    """
    return Settings()
