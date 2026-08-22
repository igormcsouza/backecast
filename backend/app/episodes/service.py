from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Depends

from app.core.settings import Settings, get_settings
from app.episodes.exceptions import UnsupportedMediaTypeError
from app.episodes.repository import get_episodes_repository
from app.episodes.schemas import (
    CreateEpisodeRequest,
    CreateEpisodeResponse,
    EpisodeStatus,
    GetEpisodeSchema,
    PresignedPostSchema,
)
from app.shared.abstracts import RepositoryAbstract
from app.shared.s3 import create_presigned_post


class EpisodesService:
    def __init__(self, repository: RepositoryAbstract, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    async def list_episodes(self) -> list[GetEpisodeSchema]:
        items = await self._repository.list()
        return [GetEpisodeSchema.model_validate(item) for item in items]

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
