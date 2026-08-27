"""One-off maintenance script: backfill `duration` for episodes stuck at 0.

Why this is needed: the worker only started computing and persisting
`duration` as of the "add episode sort orders" (#17) change to
worker/handler.py / worker/audio.py. Before that, `_preprocess_audio` never
returned a duration at all, so every episode processed by an older worker
deploy is left with whatever `create_episode()` initialized `duration` to
(0) -- nothing else in the lifecycle (transcribing -> generating, or
publish()) ever touches that attribute again. This script re-probes the
original upload for any `review`/`published` episode still stuck at
duration=0 and writes the real value back, using the exact same ffprobe
helper the worker itself uses (worker/audio.py's probe_duration_seconds),
so the number matches what a freshly-processed episode would have gotten.

Run once, against real infra (needs the target account's AWS credentials
active, and a local `ffprobe`/`ffmpeg` -- the same ones baked into the
worker's container image):

    cd backend
    uv run python scripts/backfill_episode_duration.py \\
        --table backecast-prod --bucket backecast-media-prod-<account-id> \\
        --dry-run   # inspect first, then re-run without --dry-run

Only touches episodes whose `duration` is falsy (0 or missing) and whose
status is `review` or `published` -- anything still mid-pipeline is left
alone, since the worker will set it soon on its own.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from typing import Any

import boto3

# Makes `from worker import audio` resolve regardless of the caller's cwd --
# this script is meant to be run as `uv run python scripts/<this file>.py`
# from `backend/`, but importing defensively costs nothing.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker import audio  # noqa: E402

TARGET_STATUSES = {"review", "published"}


def _all_episode_items(table: Any) -> list[dict]:
    kwargs: dict[str, Any] = {
        "IndexName": "GSI1",
        "KeyConditionExpression": "GSI1PK = :pk",
        "ExpressionAttributeValues": {":pk": "EPISODE"},
    }
    items: list[dict] = []
    while True:
        response = table.query(**kwargs)
        items.extend(response["Items"])
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key


def _needs_backfill(item: dict) -> bool:
    return (
        item.get("status") in TARGET_STATUSES
        and not item.get("duration")
        and bool(item.get("audio_key"))
    )


def backfill(table_name: str, bucket: str, dry_run: bool) -> None:
    table = boto3.resource("dynamodb").Table(table_name)
    s3 = boto3.client("s3")

    candidates = [item for item in _all_episode_items(table) if _needs_backfill(item)]
    if not candidates:
        print("Nothing to backfill -- no review/published episode has duration=0.")
        return

    updated = 0
    for item in candidates:
        episode_id = item["id"]
        audio_key = item["audio_key"]
        old_duration = item.get("duration", 0)
        print(f"{episode_id}: probing s3://{bucket}/{audio_key} ...")

        suffix = os.path.splitext(audio_key)[1] or ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            s3.download_file(bucket, audio_key, tmp.name)
            new_duration = round(audio.probe_duration_seconds(tmp.name))

        print(f"{episode_id}: duration {old_duration}s -> {new_duration}s")
        updated += 1
        if dry_run:
            continue

        # Conditional on both status and the old duration value still
        # holding, so a concurrent write (e.g. the episode getting
        # reprocessed) can't be silently clobbered by this one-off script.
        # `duration` is a DynamoDB reserved keyword, so it needs the same
        # ExpressionAttributeNames placeholder treatment as `#status` --
        # can't be interpolated directly into the expression strings.
        table.update_item(
            Key={"PK": item["PK"], "SK": item["SK"]},
            UpdateExpression="SET #duration = :new",
            ConditionExpression="#status = :status AND #duration = :old",
            ExpressionAttributeNames={"#status": "status", "#duration": "duration"},
            ExpressionAttributeValues={
                ":new": new_duration,
                ":status": item["status"],
                ":old": old_duration,
            },
        )

    verb = "Would update" if dry_run else "Updated"
    print(f"{verb} {updated}/{len(candidates)} episode(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--table", required=True, help="DynamoDB table name, e.g. backecast-prod"
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="Media S3 bucket name, e.g. backecast-media-prod-<account-id>",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Probe and print what would change, without writing to DynamoDB",
    )
    args = parser.parse_args()
    backfill(args.table, args.bucket, args.dry_run)


if __name__ == "__main__":
    main()
