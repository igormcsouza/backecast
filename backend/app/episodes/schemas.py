"""Define the schemas for the episodes crud."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class EpisodeStatus(str, Enum):
    """Lifecycle states an episode item moves through.

    UPLOADING (Phase 3) -> PROCESSING -> PROCESSED_STUB (Phase 4 — the
    worker just proves the S3 -> SQS -> worker wiring end to end; no AI
    yet). Later phases (AI metadata generation, publishing) add REJECTED,
    FAILED, REVIEW, PUBLISHED. Declared as a str-enum now so schemas are
    typed while the value stored in DynamoDB stays a plain string.
    """

    UPLOADING = "uploading"
    PROCESSING = "processing"
    PROCESSED_STUB = "processed-stub"


class GetEpisodeSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    status: EpisodeStatus
    duration: int
    release_date: str
    audio_url: str | None = None
    image_url: str | None = None
    created_at: str
    updated_at: str


class CreateEpisodeRequest(BaseModel):
    """What the admin submits to start an upload.

    The audio bytes themselves never go through the API — they go straight
    to S3 via the presigned POST this request kicks off. filename/content_type
    are only used to pick the S3 key extension and validate the content type.
    """

    filename: str
    content_type: str


class PresignedPostSchema(BaseModel):
    """Mirrors boto3's generate_presigned_post() return shape."""

    url: str
    fields: dict[str, str]


class CreateEpisodeResponse(BaseModel):
    id: str
    status: EpisodeStatus
    upload: PresignedPostSchema
