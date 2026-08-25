"""Manage the episodes table in DynamoDB.

This is the place where the logic for interacting with the episodes
table in DynamoDB is implemented. The EpisodesRepository class provides
methods to perform CRUD operations on the episodes data stored in the
DynamoDB table.
"""

# `from __future__ import annotations` is required here, not just stylistic:
# without it, every `-> list[...]` annotation on a method declared *after*
# `list()` in this class body resolves `list` to that already-defined
# method object (class bodies are their own namespace, evaluated top to
# bottom) instead of the builtin, raising `TypeError: 'function' object is
# not subscriptable` at import time. PEP 563 defers annotation evaluation
# entirely, sidestepping the shadowing.
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends

from app.episodes.exceptions import (
    EpisodeAlreadyExistsError,
    EpisodeNotEditableError,
    EpisodeNotPublishableError,
)
from app.episodes.schemas import EpisodeStatus
from app.shared.abstracts import RepositoryAbstract
from app.shared.dynamodb import get_table


def _encode_cursor(last_evaluated_key: dict) -> str:
    """Wrap a raw DynamoDB LastEvaluatedKey into an opaque client-facing
    token — the client must never see PK/SK/GSI1PK/GSI1SK shapes."""
    return base64.urlsafe_b64encode(json.dumps(last_evaluated_key).encode()).decode()


def _decode_cursor(cursor: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())


class EpisodesRepository(RepositoryAbstract):
    def __init__(self, table: Any) -> None:
        self._table = table

    async def list(self) -> list[dict]:
        """List every episode via GSI1 (creation order) — the admin
        review-queue view without a status filter."""
        response = await self._table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={":pk": "EPISODE"},
        )
        return response["Items"]

    async def list_by_status(self, status: str) -> list[dict]:
        """Admin queue filtered to one status (e.g. `review`).

        Still a GSI1 query + FilterExpression, same index as `list()` —
        see `list_published_page()`'s docstring for why this codebase
        doesn't add a second, status-keyed GSI just for this.
        """
        response = await self._table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            FilterExpression="#status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":pk": "EPISODE", ":status": status},
        )
        return response["Items"]

    async def list_published_page(
        self, limit: int, cursor: str | None
    ) -> tuple[list[dict], str | None]:
        """One page of `status=published` episodes, newest-created first.

        Reuses GSI1 (already partitioned on a constant `"EPISODE"` key,
        sorted by `{created_at}#{id}`) with a FilterExpression instead of
        adding a second, status-keyed GSI. The trade-off: DynamoDB's
        `Limit` caps items *scanned* per call, not items *returned* after
        the filter, so a page can legitimately come back with fewer than
        `limit` items (even zero) while `cursor` is still non-None — the
        client just asks again. Chosen over a GSI2 keyed by status because
        every status transition (worker's `_transition()` in
        worker/handler.py, this repository's own `publish()`) would then
        have to keep a second index attribute in sync, and this table's
        expected episode count is small enough at MVP scale that the extra
        scanned-but-filtered-out items cost is negligible. Revisit with a
        GSI2 (`GSI2PK="STATUS#<status>"`) if the catalog grows large enough
        for that to matter.
        """
        kwargs: dict[str, Any] = {
            "IndexName": "GSI1",
            "KeyConditionExpression": "GSI1PK = :pk",
            "FilterExpression": "#status = :status",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {
                ":pk": "EPISODE",
                ":status": EpisodeStatus.PUBLISHED.value,
            },
            # GSI1SK is `{created_at}#{id}` — DynamoDB queries ascending by
            # sort key by default, which is oldest-first; this flips it to
            # match the "newest-created first" contract this method (and
            # its docstring, and every caller) already assumes.
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)

        response = await self._table.query(**kwargs)

        next_cursor = None
        if "LastEvaluatedKey" in response:
            next_cursor = _encode_cursor(response["LastEvaluatedKey"])
        return response["Items"], next_cursor

    async def get(self, episode_id: str) -> dict | None:
        response = await self._table.get_item(
            Key={"PK": f"EPISODE#{episode_id}", "SK": f"EPISODE#{episode_id}"}
        )
        return response.get("Item")

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

    async def update(
        self, episode_id: str, fields: dict, *, expected_status: str | None = None
    ) -> dict:
        """Partial update (the `PATCH /episodes/{id}` review-edit path).

        Builds a `SET` expression from whatever `fields` the caller passes
        via placeholders (`#f0`, `:v0`, ...) rather than interpolating
        attribute names directly — same reservation-safe pattern the
        worker's `_transition()` uses for its `extra_attributes`, needed
        here too since `status` (among others) is a DynamoDB reserved word.
        Always stamps `updated_at`, mirroring every other write path in
        this table.

        `expected_status`, when given, adds the same conditional-write
        guard `publish()` uses: without it, a caller-side "is this episode
        still `review`?" check and this write are two separate round-trips,
        leaving a race where the status changes in between (e.g. a
        concurrent Publish) and this update silently overwrites metadata on
        an episode no longer in the editable state. The condition makes
        that race fail loudly instead.
        """
        now = datetime.now(UTC).isoformat()
        set_clauses = ["updated_at = :now"]
        names: dict[str, str] = {}
        values: dict[str, Any] = {":now": now}
        for i, (attr, value) in enumerate(fields.items()):
            name_placeholder, value_placeholder = f"#f{i}", f":v{i}"
            names[name_placeholder] = attr
            values[value_placeholder] = value
            set_clauses.append(f"{name_placeholder} = {value_placeholder}")

        kwargs: dict[str, Any] = {
            "Key": {"PK": f"EPISODE#{episode_id}", "SK": f"EPISODE#{episode_id}"},
            "UpdateExpression": "SET " + ", ".join(set_clauses),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
            "ReturnValues": "ALL_NEW",
        }
        if expected_status is not None:
            kwargs["ConditionExpression"] = "#status = :expected_status"
            kwargs["ExpressionAttributeNames"] = {**names, "#status": "status"}
            kwargs["ExpressionAttributeValues"] = {
                **values,
                ":expected_status": expected_status,
            }

        try:
            response = await self._table.update_item(**kwargs)
        except self._table.meta.client.exceptions.ConditionalCheckFailedException as e:
            raise EpisodeNotEditableError() from e
        return response["Attributes"]

    async def publish(self, episode_id: str) -> dict:
        """`review -> published`, conditional on the item currently being
        `review` — the same conditional-write idempotency primitive the
        worker's state machine uses, applied here so a duplicate Publish
        click (or a retried request) fails loudly (409, via
        EpisodeNotPublishableError) instead of silently no-opping or
        double-transitioning."""
        now = datetime.now(UTC).isoformat()
        try:
            response = await self._table.update_item(
                Key={"PK": f"EPISODE#{episode_id}", "SK": f"EPISODE#{episode_id}"},
                UpdateExpression="SET #status = :to, updated_at = :now",
                ConditionExpression="#status = :from",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":to": EpisodeStatus.PUBLISHED.value,
                    ":from": EpisodeStatus.REVIEW.value,
                    ":now": now,
                },
                ReturnValues="ALL_NEW",
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException as e:
            raise EpisodeNotPublishableError() from e
        return response["Attributes"]


def get_episodes_repository(table: Any = Depends(get_table)) -> EpisodesRepository:
    return EpisodesRepository(table)
