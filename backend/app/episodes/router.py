"""Router for episodes endpoints"""

from fastapi import APIRouter, Depends

from app.episodes.schemas import GetEpisodeSchema
from app.episodes.service import get_episodes_service, EpisodesService
from app.episodes.exceptions import EpisodesRepositoryError


episodes_router = APIRouter(prefix="/api/v1/episodes", tags=["Episodes"])


@episodes_router.get("", summary="Get the all the episodes")
async def get_episodes(
    service: EpisodesService = Depends(get_episodes_service),
) -> list[GetEpisodeSchema]:
    """Get all the episodes"""
    try:
        return await service.list_episodes()
    except Exception as e:
        raise EpisodesRepositoryError() from e


@episodes_router.get("/{episode_id}", summary="Get a specific episode")
async def get_episode(episode_id: str):
    """Get a specific episode"""
    return


@episodes_router.post("", summary="Create a new episode")
async def create_episode():
    """Create a new episode"""
    return {"message": "Create a new episode"}


@episodes_router.put("/{episode_id}", summary="Update a specific episode")
async def update_episode(episode_id: str):
    """Update a specific episode"""
    return {"message": f"Update episode with ID: {episode_id}"}


@episodes_router.delete("/{episode_id}", summary="Delete a specific episode")
async def delete_episode(episode_id: str):
    """Delete a specific episode"""
    return {"message": f"Delete episode with ID: {episode_id}"}
