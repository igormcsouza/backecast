"""Manage the episodes table in DynamoDB.

This is the place where the logic for interacting with the episodes
table in DynamoDB is implemented. The EpisodesRepository class provides
methods to perform CRUD operations on the episodes data stored in the
DynamoDB table.
"""

from typing import Any

from fastapi import Depends

from app.episodes.exceptions import EpisodeAlreadyExistsError
from app.shared.abstracts import RepositoryAbstract
from app.shared.dynamodb import get_table


class EpisodesRepository(RepositoryAbstract):
    def __init__(self, table: Any) -> None:
        self._table = table

    async def list(self) -> list[dict]:
        response = await self._table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={":pk": "EPISODE"},
        )
        return response["Items"]

    async def create(self, item: dict) -> dict:
        # ConditionExpression makes this a create-or-fail instead of a
        # silent overwrite — the same idempotency primitive the Phase 4
        # worker will reuse for status transitions on repeated SQS delivery.
        try:
            await self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK)",
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException as e:
            raise EpisodeAlreadyExistsError() from e
        return item


def get_episodes_repository(table: Any = Depends(get_table)) -> EpisodesRepository:
    return EpisodesRepository(table)
