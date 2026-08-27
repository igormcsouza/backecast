"""Define the schemas for the episodes crud."""

from enum import Enum

from typing import Any
from pydantic import BaseModel, ConfigDict, HttpUrl, model_validator


class EpisodeStatus(str, Enum):
    """Lifecycle states an episode item moves through.

    UPLOADING (Phase 3) -> PROCESSING (Phase 4 wiring proof) -> Phase 5's
    real AI chain: TRANSCRIBING -> GENERATING -> REVIEW -> Phase 6's
    PUBLISHED (an admin moving a REVIEW episode live, via
    `POST /episodes/{id}/publish` — the only place this transition
    happens, always conditional on the item currently being REVIEW).
    REJECTED is a terminal state reached straight from PROCESSING when
    ffmpeg's duration probe finds the upload over the transcription-length
    cap (no transcription attempt, no cost). FAILED is terminal for any
    other unrecoverable error at any stage — the worker lets the SQS
    message go to the DLQ rather than swallowing the exception, so a human
    can inspect why.
    Declared as a str-enum so schemas are typed while the value stored in
    DynamoDB stays a plain string.
    """

    UPLOADING = "uploading"
    PROCESSING = "processing"
    TRANSCRIBING = "transcribing"
    GENERATING = "generating"
    REVIEW = "review"
    PUBLISHED = "published"
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
    # Phase 6 addition: the worker (worker/handler.py's generating -> review
    # transition) has always written resources into the DynamoDB item, but
    # this schema never surfaced them — no reader needed them until now.
    # The admin review view needs to show and edit them, and the public
    # page needs to render them, so they're part of the read shape.
    resources: list[Resource] = []
    created_at: str
    updated_at: str

    @model_validator(mode="before")
    @classmethod
    def backfill_missing_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("release_date") and data.get("status") == EpisodeStatus.PUBLISHED.value:
                data["release_date"] = data.get("updated_at") or data.get("created_at") or ""
        return data


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


class UpdateEpisodeRequest(BaseModel):
    """Admin edits to an episode's AI-generated metadata, made from the
    review view before publishing. Every field is optional — a PATCH only
    touches the fields it's given (`None` means "leave as is", not "clear
    this field"), so the frontend can send just the field the reviewer
    changed instead of the whole episode.
    """

    title: str | None = None
    description: str | None = None
    resources: list[Resource] | None = None


class TranscriptSchema(BaseModel):
    """Presigned GET for the raw transcript S3 object the worker wrote
    during transcription."""

    url: str


class PaginatedEpisodesResponse(BaseModel):
    """The public `GET /episodes` list shape.

    `cursor` is an opaque, base64-encoded token wrapping DynamoDB's
    `LastEvaluatedKey` — clients pass it back verbatim as `?cursor=...` to
    fetch the next page and must never construct or inspect it themselves.
    `None` means there is no next page.
    """

    items: list[GetEpisodeSchema]
    cursor: str | None = None
