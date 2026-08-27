import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Depends

from app.core.settings import Settings, get_settings
from app.episodes.exceptions import (
    EpisodeNotEditableError,
    EpisodeNotFoundError,
    UnsupportedMediaTypeError,
)
from app.episodes.repository import get_episodes_repository
from app.episodes.schemas import (
    CreateEpisodeRequest,
    CreateEpisodeResponse,
    EpisodeStatus,
    GetEpisodeSchema,
    PaginatedEpisodesResponse,
    PresignedPostSchema,
    TranscriptSchema,
    UpdateEpisodeRequest,
)
from app.shared.abstracts import RepositoryAbstract
from app.shared.s3 import create_presigned_get, create_presigned_post

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50


class EpisodesService:
    def __init__(self, repository: RepositoryAbstract, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    async def _with_audio_url(self, item: dict) -> dict:
        """Swap the raw `audio_key` for a time-limited presigned GET URL
        the browser can stream (and seek — S3 honors Range requests on a
        presigned GET) directly from. Done per-request rather than stored,
        since a stored URL would just go stale."""
        audio_key = item.get("audio_key")
        if not audio_key:
            return item
        item = dict(item)
        item["audio_url"] = await create_presigned_get(
            bucket=self._settings.media_bucket_name, key=audio_key
        )
        return item

    async def list_public_episodes(
        self, limit: int, cursor: str | None
    ) -> PaginatedEpisodesResponse:
        """`GET /episodes` — public, `status=published` only. See
        EpisodesRepository.list_published_page for the pagination/cursor
        design."""
        items, next_cursor = await self._repository.list_published_page(limit, cursor)
        # Independent per-item presigns — run concurrently rather than
        # paying `limit` sequential round-trips.
        items = list(await asyncio.gather(*(self._with_audio_url(i) for i in items)))
        return PaginatedEpisodesResponse(
            items=[GetEpisodeSchema.model_validate(item) for item in items],
            cursor=next_cursor,
        )

    async def get_public_episode(self, episode_id: str) -> GetEpisodeSchema:
        """`GET /episodes/{id}` — public. 404s for a missing id *and* for
        one that exists but isn't published yet, so this route can never
        be used to confirm an unpublished episode's existence."""
        item = await self._repository.get(episode_id)
        if item is None or item.get("status") != EpisodeStatus.PUBLISHED.value:
            raise EpisodeNotFoundError()
        item = await self._with_audio_url(item)
        return GetEpisodeSchema.model_validate(item)

    async def list_admin_episodes(
        self, status: EpisodeStatus | None
    ) -> list[GetEpisodeSchema]:
        """`GET /episodes/admin` — admin-only. `?status=review` is the
        review-queue view; no filter lists every episode regardless of
        status."""
        if status is not None:
            items = await self._repository.list_by_status(status.value)
        else:
            items = await self._repository.list()
        return [GetEpisodeSchema.model_validate(item) for item in items]

    async def get_admin_episode(self, episode_id: str) -> GetEpisodeSchema:
        """`GET /episodes/{id}/admin` — admin-only, any status. Used both
        for the post-upload status-polling view and the review/edit view."""
        item = await self._repository.get(episode_id)
        if item is None:
            raise EpisodeNotFoundError()
        item = await self._with_audio_url(item)
        return GetEpisodeSchema.model_validate(item)

    async def get_public_transcript_url(self, episode_id: str) -> TranscriptSchema:
        """`GET /episodes/{id}/transcript` — public. 404s for anything not
        `status=published`, same rule as `get_public_episode`, so this
        route can't be used to confirm an unpublished episode's existence
        either."""
        item = await self._repository.get(episode_id)
        if item is None or item.get("status") != EpisodeStatus.PUBLISHED.value:
            raise EpisodeNotFoundError()
        key = f"{self._settings.transcript_key_prefix}{episode_id}.json"
        url = await create_presigned_get(
            bucket=self._settings.media_bucket_name, key=key
        )
        return TranscriptSchema(url=url)

    async def get_transcript_url(self, episode_id: str) -> TranscriptSchema:
        """`GET /episodes/{id}/transcript` — admin-only. The transcript key
        is deterministic (worker writes it the same way) and never stored
        on the item, so it's derived here rather than read off the repo."""
        item = await self._repository.get(episode_id)
        if item is None:
            raise EpisodeNotFoundError()
        key = f"{self._settings.transcript_key_prefix}{episode_id}.json"
        url = await create_presigned_get(
            bucket=self._settings.media_bucket_name, key=key
        )
        return TranscriptSchema(url=url)

    async def update_episode(
        self, episode_id: str, payload: UpdateEpisodeRequest
    ) -> GetEpisodeSchema:
        """`PATCH /episodes/{id}` — admin-only, review-edit metadata.
        Only allowed while `status=review`: editing already-published (or
        still in-flight) episodes isn't a flow this MVP supports."""
        item = await self._repository.get(episode_id)
        if item is None:
            raise EpisodeNotFoundError()
        if item.get("status") != EpisodeStatus.REVIEW.value:
            raise EpisodeNotEditableError()

        fields: dict = {}
        if payload.title is not None:
            fields["title"] = payload.title
        if payload.description is not None:
            fields["description"] = payload.description
        if payload.resources is not None:
            fields["resources"] = [
                resource.model_dump(mode="json") for resource in payload.resources
            ]

        if not fields:
            item = await self._with_audio_url(item)
            return GetEpisodeSchema.model_validate(item)

        # `expected_status` closes the check-then-act race between the read
        # above and this write: the repository's conditional write is the
        # real guard, this early check is just a friendlier fast path.
        updated = await self._repository.update(
            episode_id, fields, expected_status=EpisodeStatus.REVIEW.value
        )
        updated = await self._with_audio_url(updated)
        return GetEpisodeSchema.model_validate(updated)

    async def publish_episode(self, episode_id: str) -> GetEpisodeSchema:
        """`POST /episodes/{id}/publish` — admin-only, `review -> published`.
        A missing episode is a 404; an episode that exists but isn't
        `review` surfaces as a 409 from the repository's conditional write
        (EpisodeNotPublishableError)."""
        item = await self._repository.get(episode_id)
        if item is None:
            raise EpisodeNotFoundError()
        updated = await self._repository.publish(episode_id)
        updated = await self._with_audio_url(updated)
        return GetEpisodeSchema.model_validate(updated)

    async def create_episode(
        self, payload: CreateEpisodeRequest
    ) -> CreateEpisodeResponse:
        if payload.content_type not in self._settings.allowed_content_types:
            raise UnsupportedMediaTypeError()

        episode_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        extension = Path(payload.filename).suffix or ".mp3"
        audio_key = f"uploads/{episode_id}{extension}"

        item = {
            "PK": f"EPISODE#{episode_id}",
            "SK": f"EPISODE#{episode_id}",
            "GSI1PK": "EPISODE",
            "GSI1SK": f"{now}#{episode_id}",
            "id": episode_id,
            "title": "",
            "description": "",
            "status": EpisodeStatus.UPLOADING.value,
            "duration": 0,
            "release_date": "",
            "audio_url": None,
            "audio_key": audio_key,
            "image_url": None,
            "created_at": now,
            "updated_at": now,
        }

        # Write the item before signing the upload: a failed presign never
        # leaves a DB row promising an upload nothing can complete, and a
        # failed write never hands out a URL for a key nothing is tracking.
        await self._repository.create(item)

        presigned = await create_presigned_post(
            bucket=self._settings.media_bucket_name,
            key=audio_key,
            content_type=payload.content_type,
            max_bytes=self._settings.max_upload_bytes,
        )

        return CreateEpisodeResponse(
            id=episode_id,
            status=EpisodeStatus.UPLOADING,
            upload=PresignedPostSchema(
                url=presigned["url"], fields=presigned["fields"]
            ),
        )


def get_episodes_service(
    repository: RepositoryAbstract = Depends(get_episodes_repository),
    settings: Settings = Depends(get_settings),
) -> EpisodesService:
    return EpisodesService(repository, settings)
