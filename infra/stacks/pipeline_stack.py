"""S3 -> SQS -> worker Lambda event pipeline, with a DLQ.

Cost note (CLAUDE.md guardrail): SQS and Lambda are both pay-per-use with a
generous perpetual free tier (1M SQS requests/month, 1M Lambda
requests + 400,000 GB-seconds/month) — nothing here has an always-on hourly
charge, so provisioning this stack itself needs no approval beyond the usual
"state the cost" rule. What Phase 5 adds that *does* cost real money per
invocation is the worker's own OpenAI/LLM calls (~$0.003/min of audio
transcribed, ~$0.18/hour-long episode, plus a small per-episode LLM token
cost for metadata generation) — see worker/transcription.py and
worker/metadata.py's docstrings for the numbers, and SESSIONS.md for the
full cost writeup. Nothing in *this* CDK stack spends money on its own;
AI_STUB=1 in docker-compose (and hard-coded in the test suite) keeps local
dev and CI from ever placing a real API call.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from constructs import Construct

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"

# The worker Lambda's own timeout: how long ONE invocation (one batch) may
# run. Phase 4's worker was a synchronous stub (a couple of conditional
# DynamoDB updates) sized at 30s. Phase 5's worker does real work inside
# that one invocation — download from S3, ffmpeg transcode, an OpenAI
# transcription call, a LangChain metadata-generation call, another S3
# write — all synchronously, no async job orchestration. 5 minutes is
# generous headroom for a ~25-minute episode (the transcription-length cap
# enforced in worker/audio.py) without being anywhere near Lambda's own
# 15-minute hard ceiling. Per the comment below, the visibility timeout is
# derived from this value, so raising/lowering WORKER_TIMEOUT alone keeps
# the two in sync.
WORKER_TIMEOUT = Duration.minutes(5)

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

# How many messages one worker invocation may receive at once. The handler
# processes batch records sequentially (see worker/handler.py), so total
# invocation time is roughly BATCH_SIZE * (per-episode processing time), not
# a single episode's time. Phase 5's per-message cost is minutes of
# ffmpeg+OpenAI+LLM work, close to WORKER_TIMEOUT on its own for a
# near-cap-length episode — batching more than one together risks the
# Lambda's own timeout killing the invocation mid-batch (which fails every
# message in it, including ones that already finished, since no
# batchItemFailures gets reported for a hard timeout). Kept at 1 so
# WORKER_TIMEOUT bounds a single invocation's worst case exactly.
BATCH_SIZE = 1


class PipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        table: dynamodb.Table,
        bucket: s3.Bucket,
        openai_api_key_param: ssm.IStringParameter,
        llm_api_key_param: ssm.IStringParameter,
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

        # DockerImageFunction, not PythonFunction/zip (unlike ApiFunction in
        # api_stack.py) — this Lambda needs the ffmpeg/ffprobe binaries
        # bundled into it (worker/audio.py, worker/Dockerfile explain why).
        # Build context is BACKEND_DIR so the Dockerfile can COPY
        # pyproject.toml/uv.lock/app/worker from there.
        worker_function = lambda_.DockerImageFunction(
            self,
            "WorkerFunction",
            code=lambda_.DockerImageCode.from_image_asset(
                directory=str(BACKEND_DIR),
                file="worker/Dockerfile",
            ),
            environment={
                "STAGE": stage,
                "TABLE_NAME": table.table_name,
                "AI_STUB": "0",  # real infra: no stub. Local dev sets AI_STUB=1 in docker-compose.
                "OPENAI_API_KEY_PARAM_NAME": openai_api_key_param.parameter_name,
                "LLM_API_KEY_PARAM_NAME": llm_api_key_param.parameter_name,
            },
            timeout=WORKER_TIMEOUT,
            # 256MB was plenty for Phase 4's stub (a couple of DynamoDB
            # calls). ffmpeg transcoding and buffering an audio file in
            # /tmp need real headroom; 1024MB is comfortable for a
            # 25-minute episode without over-provisioning (Lambda cost
            # scales with memory x duration, and this is still free-tier
            # territory at this project's volume).
            memory_size=1024,
        )
        # Phase 5 needs real permissions the Phase 4 stub didn't: read the
        # raw upload (to ffmpeg-preprocess it) and write the transcript,
        # both scoped to their own key prefixes rather than a blanket
        # grant_read_write on the whole bucket — the worker never needs to
        # touch anything outside uploads/ or transcripts/.
        table.grant_read_write_data(worker_function)
        bucket.grant_read(worker_function, objects_key_pattern="uploads/*")
        bucket.grant_put(worker_function, objects_key_pattern="transcripts/*")
        openai_api_key_param.grant_read(worker_function)
        llm_api_key_param.grant_read(worker_function)

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
