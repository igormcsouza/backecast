"""Define the schemas for the episodes crud."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, HttpUrl


class EpisodeStatus(str, Enum):
    """Lifecycle states an episode item moves through.

    UPLOADING (Phase 3) -> PROCESSING (Phase 4 wiring proof) -> Phase 5's
    real AI chain: TRANSCRIBING -> GENERATING -> REVIEW. REJECTED is a
    terminal state reached straight from PROCESSING when ffmpeg's duration
    probe finds the upload over the transcription-length cap (no
    transcription attempt, no cost). FAILED is terminal for any other
    unrecoverable error at any stage — the worker lets the SQS message go
    to the DLQ rather than swallowing the exception, so a human can inspect
    why. PUBLISHED (a human moving a REVIEW episode live) is a later phase.
    Declared as a str-enum so schemas are typed while the value stored in
    DynamoDB stays a plain string.
    """

    UPLOADING = "uploading"
    PROCESSING = "processing"
    TRANSCRIBING = "transcribing"
    GENERATING = "generating"
    REVIEW = "review"
    REJECTED = "rejected"
    FAILED = "failed"


class Resource(BaseModel):
    """One link surfaced alongside an episode (show notes, mentioned tools, etc.).

    `HttpUrl` (not `str`) is deliberate: it's the Pydantic validation that
    Phase 5's mandatory sabotage exercise leans on — an LLM (or a stubbed
    one, for the exercise) returning a malformed URL or a missing field
    fails *here*, before anything is persisted, rather than silently
    storing garbage a public episode page would later render as a dead or
    dangerous link.
    """

    label: str
    url: HttpUrl


class EpisodeMetadata(BaseModel):
    """The LangChain metadata chain's structured output shape.

    `.with_structured_output(EpisodeMetadata)` makes the LLM call return
    (or raise, on a shape mismatch) an instance of exactly this model —
    Pydantic validates it before a single field is written to DynamoDB.
    """

    title: str
    description: str
    resources: list[Resource] = []


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
