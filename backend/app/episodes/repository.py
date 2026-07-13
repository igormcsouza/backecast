"""Manage the episodes table in DynamoDB.

This is the place where the logic for interacting with the episodes
table in DynamoDB is implemented. The EpisodesRepository class provides
methods to perform CRUD operations on the episodes data stored in the
DynamoDB table.
"""

from typing import Any

from fastapi import Depends

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


def get_episodes_repository(table: Any = Depends(get_table)) -> EpisodesRepository:
    return EpisodesRepository(table)
