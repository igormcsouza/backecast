from fastapi import Depends

from app.shared.abstracts import RepositoryAbstract
from app.episodes.repository import get_episodes_repository
from app.episodes.schemas import GetEpisodeSchema


class EpisodesService:
    def __init__(self, repository: RepositoryAbstract) -> None:
        self._repository = repository

    async def list_episodes(self) -> list[GetEpisodeSchema]:
        items = await self._repository.list()
        return [GetEpisodeSchema.model_validate(item) for item in items]


def get_episodes_service(
    repository: RepositoryAbstract = Depends(get_episodes_repository),
) -> EpisodesService:
    return EpisodesService(repository)
