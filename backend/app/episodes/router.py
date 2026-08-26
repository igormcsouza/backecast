"""Router for episodes endpoints.

Route declaration order matters for the literal-vs-parameterized paths
below: `GET /admin` must be declared before `GET /{episode_id}` (both are
single path segments after the prefix), or a request for `/episodes/admin`
would be swallowed by the `{episode_id}` route with `episode_id="admin"`.
"""

from fastapi import APIRouter, Depends, Query

from app.core.auth import require_admin_key
from app.episodes.exceptions import EpisodesRepositoryError
from app.episodes.schemas import (
    CreateEpisodeRequest,
    CreateEpisodeResponse,
    EpisodeStatus,
    GetEpisodeSchema,
    PaginatedEpisodesResponse,
    TranscriptSchema,
    UpdateEpisodeRequest,
)
from app.episodes.service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    EpisodesService,
    get_episodes_service,
)

episodes_router = APIRouter(prefix="/api/v1/episodes", tags=["Episodes"])


@episodes_router.get("", summary="List published episodes (public, cursor-paginated)")
async def get_episodes(
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(default=None),
    service: EpisodesService = Depends(get_episodes_service),
) -> PaginatedEpisodesResponse:
    """Public: only `status=published` episodes, newest-created first.
    `cursor` is the opaque token from a previous response's `cursor`
    field — omit it for the first page."""
    try:
        return await service.list_public_episodes(limit, cursor)
    except Exception as e:
        raise EpisodesRepositoryError() from e


@episodes_router.get(
    "/admin",
    summary="List episodes for the admin review queue",
    dependencies=[Depends(require_admin_key)],
)
async def get_admin_episodes(
    status: EpisodeStatus | None = Query(default=None),
    service: EpisodesService = Depends(get_episodes_service),
) -> list[GetEpisodeSchema]:
    """Admin-only: every episode, or filter with `?status=review` for the
    review queue."""
    try:
        return await service.list_admin_episodes(status)
    except Exception as e:
        raise EpisodesRepositoryError() from e


@episodes_router.get("/{episode_id}", summary="Get a published episode (public)")
async def get_episode(
    episode_id: str,
    service: EpisodesService = Depends(get_episodes_service),
) -> GetEpisodeSchema:
    """Public detail route backing the streaming page. 404s for anything
    not `status=published`, including episodes that exist but aren't
    published yet — this route can never confirm an unpublished episode's
    existence."""
    return await service.get_public_episode(episode_id)


@episodes_router.get(
    "/{episode_id}/admin",
    summary="Get any episode by id, any status (admin)",
    dependencies=[Depends(require_admin_key)],
)
async def get_admin_episode(
    episode_id: str,
    service: EpisodesService = Depends(get_episodes_service),
) -> GetEpisodeSchema:
    """Admin variant of the detail route — works for any status. Used for
    post-upload status polling and for loading the review/edit view."""
    return await service.get_admin_episode(episode_id)


@episodes_router.get(
    "/{episode_id}/transcript",
    summary="Get a presigned URL for a published episode's transcript (public)",
)
async def get_episode_transcript(
    episode_id: str,
    service: EpisodesService = Depends(get_episodes_service),
) -> TranscriptSchema:
    """Public: presigned GET for the raw transcript S3 object the worker
    wrote during transcription. 404s for anything not `status=published`,
    same rule as the public episode detail route."""
    return await service.get_public_transcript_url(episode_id)


@episodes_router.get(
    "/{episode_id}/transcript/admin",
    summary="Get a presigned URL for any episode's transcript, any status (admin)",
    dependencies=[Depends(require_admin_key)],
)
async def get_admin_episode_transcript(
    episode_id: str,
    service: EpisodesService = Depends(get_episodes_service),
) -> TranscriptSchema:
    """Admin variant — works for any status, used by the review view."""
    return await service.get_transcript_url(episode_id)


@episodes_router.post(
    "",
    status_code=201,
    summary="Create a new episode",
    dependencies=[Depends(require_admin_key)],
)
async def create_episode(
    payload: CreateEpisodeRequest,
    service: EpisodesService = Depends(get_episodes_service),
) -> CreateEpisodeResponse:
    """Create a new episode (status=uploading) and return a presigned POST."""
    return await service.create_episode(payload)


@episodes_router.patch(
    "/{episode_id}",
    summary="Edit an episode's AI-generated metadata (admin, review only)",
    dependencies=[Depends(require_admin_key)],
)
async def update_episode(
    episode_id: str,
    payload: UpdateEpisodeRequest,
    service: EpisodesService = Depends(get_episodes_service),
) -> GetEpisodeSchema:
    """Admin-only: edit title/description/resources before publish. 409s
    if the episode isn't `status=review`."""
    return await service.update_episode(episode_id, payload)


@episodes_router.post(
    "/{episode_id}/publish",
    summary="Publish an episode (admin, review -> published)",
    dependencies=[Depends(require_admin_key)],
)
async def publish_episode(
    episode_id: str,
    service: EpisodesService = Depends(get_episodes_service),
) -> GetEpisodeSchema:
    """Admin-only: `review -> published`. 409s if the episode isn't
    `status=review` (already published, or still processing)."""
    return await service.publish_episode(episode_id)


@episodes_router.delete("/{episode_id}", summary="Delete a specific episode")
async def delete_episode(episode_id: str):
    """Delete a specific episode"""
    return {"message": f"Delete episode with ID: {episode_id}"}
