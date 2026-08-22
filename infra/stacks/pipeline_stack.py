"""S3 -> SQS -> worker Lambda event pipeline, with a DLQ.

Cost note (CLAUDE.md guardrail): SQS and Lambda are both pay-per-use with a
generous perpetual free tier (1M SQS requests/month, 1M Lambda
requests + 400,000 GB-seconds/month) — nothing here has an always-on hourly
charge, so nothing in this stack needs approval beyond the usual "state the
cost" rule, and there's nothing to state: at this project's volume it's $0.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sqs as sqs
from aws_cdk.aws_lambda_python_alpha import BundlingOptions, PythonFunction
from constructs import Construct

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"

# The worker Lambda's own timeout: how long ONE invocation (one batch) may
# run. Phase 4's worker is a synchronous stub (a couple of conditional
# DynamoDB updates), so 30s is generous headroom rather than a measured
# budget. Phase 5 (ffmpeg + transcription + an LLM call in the same
# invocation) will need minutes, not seconds — and per the comment below,
# the visibility timeout must be revisited in lockstep when that happens.
WORKER_TIMEOUT = Duration.seconds(30)

# Visibility timeout ~= 6x the worker's own timeout. The mechanism: once SQS
# hands a message to a consumer, that message becomes invisible to every
# other consumer for exactly this long. If the worker is still processing
# when the timer runs out, SQS assumes the consumer died and redelivers the
# same message — to this worker or another one — causing duplicate
# processing (this is exactly what Phase 4's sabotage exercise #2
# reproduces on purpose, with the timeout set deliberately too low). Sizing
# it at ~6x the Lambda timeout gives headroom for retries, cold starts, and
# GC pauses without the visibility window racing a single slow-but-healthy
# invocation, while still bounding how long a genuinely stuck message can
# block reprocessing.
VISIBILITY_TIMEOUT = Duration.seconds(int(WORKER_TIMEOUT.to_seconds()) * 6)

# After this many failed receives (handler raised, or reported the message
# back as a batch item failure), SQS stops retrying and moves the message to
# the DLQ instead of redelivering it forever. Sabotage exercise #1 forces
# every receive to fail on purpose and watches this counter run out.
MAX_RECEIVE_COUNT = 3

# How many messages one worker invocation may receive at once. A larger
# batch amortizes Lambda invocation overhead across more work but also means
# one slow/failing message in the batch (partial failure) delays the whole
# batch's visibility-timeout clock together — 5 is a reasonable stub-worker
# default, revisited once Phase 5's per-message cost is known.
BATCH_SIZE = 5


class PipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        table: dynamodb.Table,
        bucket: s3.Bucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # DLQ ("dead-letter queue" — the RabbitMQ analogue is a DLX): a
        # parking lot for messages the worker could not process after
        # MAX_RECEIVE_COUNT attempts. Keeping them (instead of dropping them)
        # is the whole point — a human can inspect *why* a specific message
        # kept failing instead of it silently vanishing.
        self.dlq = sqs.Queue(
            self,
            "MediaDLQ",
            queue_name=f"backecast-{stage}-media-dlq",
            retention_period=Duration.days(14),
        )

        self.queue = sqs.Queue(
            self,
            "MediaQueue",
            queue_name=f"backecast-{stage}-media-queue",
            visibility_timeout=VISIBILITY_TIMEOUT,
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=MAX_RECEIVE_COUNT, queue=self.dlq
            ),
        )

        worker_function = PythonFunction(
            self,
            "WorkerFunction",
            entry=str(BACKEND_DIR),
            index="worker/handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            bundling=BundlingOptions(
                asset_excludes=[
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "tests",
                    ".git",
                    ".dockerignore",
                    "Dockerfile",
                ],
            ),
            environment={
                "STAGE": stage,
                "TABLE_NAME": table.table_name,
            },
            timeout=WORKER_TIMEOUT,
            memory_size=256,
        )
        # No AI yet (Phase 4 scope) — the worker only flips a status field,
        # so it needs table read/write and nothing else. It doesn't even
        # need S3 access: the episode id is parsed out of the S3 object key
        # embedded in the event message, the object itself is never read.
        table.grant_read_write_data(worker_function)

        # The event source mapping is what turns "messages sitting in a
        # queue" into "Lambda invocations": AWS polls the queue on our
        # behalf and invokes worker_function with a batch. Enabling
        # report_batch_item_failures switches the contract from "the whole
        # batch succeeds or the whole batch is retried" to "tell me which
        # messages actually failed" (ReportBatchItemFailures) — see the
        # handler's own docstring for why that matters.
        worker_function.add_event_source(
            lambda_event_sources.SqsEventSource(
                self.queue,
                batch_size=BATCH_SIZE,
                report_batch_item_failures=True,
            )
        )

        # Import the media bucket *by name* into this stack instead of
        # calling add_event_notification() on the `bucket` construct passed
        # in from DataStack. That call creates a custom-resource handler in
        # whichever stack owns the Bucket construct it's invoked on — using
        # the real construct here would plant that resource in DataStack,
        # which would then need this stack's queue ARN to configure it.
        # DataStack already gets depended on by this stack (for `table` and
        # `bucket` themselves); a resource in DataStack needing something
        # from PipelineStack would make the dependency circular, which CDK
        # refuses to synth. Importing a same-named bucket scoped to *this*
        # stack sidesteps that: the only cross-stack reference left is the
        # bucket's name (a plain string export), which is one-directional.
        notification_bucket = s3.Bucket.from_bucket_name(
            self, "MediaBucketForNotifications", bucket.bucket_name
        )
        notification_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(self.queue),
            s3.NotificationKeyFilter(prefix="uploads/"),
        )

        CfnOutput(self, "MediaQueueUrl", value=self.queue.queue_url)
        CfnOutput(self, "MediaDlqUrl", value=self.dlq.queue_url)
