"""Local dev entrypoint: polls SQS in a loop and calls the SAME handler().

On AWS, there's no "worker service" — SQS invokes `worker.handler.handler`
directly via a Lambda event source mapping (configured in
`infra/stacks/pipeline_stack.py`), delivering a batch and deleting/retrying
messages itself based on what the handler returns or raises. Outside Lambda
there's no equivalent "call this function when the queue has messages"
primitive, so the docker-compose `worker` service runs this small loop
instead: poll SQS by hand, build the same event shape Lambda would have
delivered, and hand it to the identical `handler()` function.

That's the deliberate teaching point: this file re-implements the *plumbing*
Lambda gives for free (poll, invoke, then delete-or-leave-for-retry), but
never reimplements the *business logic* — that only exists once, in
handler.py, so local behavior and AWS behavior can't drift apart.
"""

from __future__ import annotations

import os
import time

import boto3
from botocore.config import Config

from app.core.logging import get_logger
from worker.handler import handler

logger = get_logger("worker.local_poller")

AWS_REGION = os.environ.get("AWS_REGION", "sa-east-1")
AWS_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL") or None
QUEUE_URL = os.environ["WORKER_QUEUE_URL"]
BATCH_SIZE = int(os.environ.get("WORKER_BATCH_SIZE", "5"))
POLL_WAIT_SECONDS = int(os.environ.get("WORKER_POLL_WAIT_SECONDS", "5"))

_sqs = boto3.client(
    "sqs",
    region_name=AWS_REGION,
    endpoint_url=AWS_ENDPOINT_URL,
    config=Config(connect_timeout=2, read_timeout=POLL_WAIT_SECONDS + 5),
)


def _to_lambda_record(message: dict) -> dict:
    """Reshape a boto3 SQS message into (the part we use of) a Lambda SQS event record."""
    return {
        "messageId": message["MessageId"],
        "receiptHandle": message["ReceiptHandle"],
        "body": message["Body"],
    }


def poll_once() -> int:
    """Receive one batch, process it, delete the successes. Returns messages received."""
    response = _sqs.receive_message(
        QueueUrl=QUEUE_URL,
        MaxNumberOfMessages=BATCH_SIZE,
        WaitTimeSeconds=POLL_WAIT_SECONDS,
    )
    messages = response.get("Messages", [])
    if not messages:
        return 0

    event = {"Records": [_to_lambda_record(m) for m in messages]}
    result = handler(event, None) or {}
    failed_ids = {f["itemIdentifier"] for f in result.get("batchItemFailures", [])}

    for message in messages:
        if message["MessageId"] in failed_ids:
            # Leave it alone: it stays invisible until the queue's
            # visibility timeout expires, then SQS redelivers it — exactly
            # what happens on AWS when the Lambda reports it as failed.
            continue
        _sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=message["ReceiptHandle"])

    return len(messages)


def run() -> None:
    logger.info("worker poller starting", extra={"queue_url": QUEUE_URL})
    while True:
        try:
            poll_once()
        except Exception:
            logger.exception("poll loop error, retrying after a short pause")
            time.sleep(2)


if __name__ == "__main__":
    run()
