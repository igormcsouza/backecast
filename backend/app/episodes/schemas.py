"""Define the schemas for the episodes crud."""

from pydantic import BaseModel, ConfigDict


class GetEpisodeSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    duration: int
    release_date: str
    audio_url: str
    image_url: str | None = None
    created_at: str
    updated_at: str
