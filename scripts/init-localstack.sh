#!/usr/bin/env bash
set -e

TABLE_NAME="backecast-dev"
REGION="sa-east-1"

if awslocal dynamodb describe-table --table-name "$TABLE_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "table $TABLE_NAME already exists, skipping"
else
  awslocal dynamodb create-table \
    --table-name "$TABLE_NAME" \
    --attribute-definitions \
      AttributeName=PK,AttributeType=S \
      AttributeName=SK,AttributeType=S \
      AttributeName=GSI1PK,AttributeType=S \
      AttributeName=GSI1SK,AttributeType=S \
    --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
    --global-secondary-indexes '[{"IndexName":"GSI1","KeySchema":[{"AttributeName":"GSI1PK","KeyType":"HASH"},{"AttributeName":"GSI1SK","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}}]' \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION"
fi

BUCKET_NAME="backecast-media-dev"

if awslocal s3api head-bucket --bucket "$BUCKET_NAME" >/dev/null 2>&1; then
  echo "bucket $BUCKET_NAME already exists, skipping"
else
  awslocal s3 mb "s3://$BUCKET_NAME" --region "$REGION"
  awslocal s3api put-bucket-cors --bucket "$BUCKET_NAME" --cors-configuration '{
    "CORSRules": [{"AllowedMethods": ["PUT","POST","GET"], "AllowedOrigins": ["*"], "AllowedHeaders": ["*"]}]
  }'
fi

# Phase 5: the worker's OpenAI/LLM API key params. With AI_STUB=1 (compose's
# default) these are never actually read — worker/transcription.py and
# worker/metadata.py short-circuit before hitting SSM — but they're seeded
# anyway so flipping AI_STUB off locally against LocalStack fails on a real
# "bad credentials" error from the provider, not a confusing "parameter not
# found". Placeholder values only; never a real key.
OPENAI_API_KEY_PARAM="/backecast/dev/openai-api-key"
LLM_API_KEY_PARAM="/backecast/dev/llm-api-key"
for param in "$OPENAI_API_KEY_PARAM" "$LLM_API_KEY_PARAM"; do
  if awslocal ssm get-parameter --name "$param" --region "$REGION" >/dev/null 2>&1; then
    echo "param $param already exists, skipping"
  else
    awslocal ssm put-parameter --name "$param" --type String \
      --value "local-stub-key-not-a-real-secret" --region "$REGION"
  fi
done

DLQ_NAME="backecast-dev-media-dlq"
QUEUE_NAME="backecast-dev-media-queue"

# Visibility timeout here must match infra/stacks/pipeline_stack.py's
# VISIBILITY_TIMEOUT (~6x the worker Lambda's own timeout) — see that file
# for why 6x. Kept as a literal here rather than derived because this script
# has no Python/CDK context to import it from; if you change one, change
# the other. maxReceiveCount likewise mirrors MAX_RECEIVE_COUNT there.
# Phase 5 raised the worker timeout from 30s to 5 minutes (ffmpeg +
# transcription + an LLM call, all in one synchronous invocation) — this
# value is that same callback, now 1800s (30 min) = 6 x 300s.
VISIBILITY_TIMEOUT="1800"
MAX_RECEIVE_COUNT="3"

if awslocal sqs get-queue-url --queue-name "$DLQ_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "queue $DLQ_NAME already exists, skipping"
  DLQ_URL=$(awslocal sqs get-queue-url --queue-name "$DLQ_NAME" --region "$REGION" --query QueueUrl --output text)
else
  DLQ_URL=$(awslocal sqs create-queue --queue-name "$DLQ_NAME" --region "$REGION" \
    --attributes MessageRetentionPeriod=1209600 --query QueueUrl --output text)
fi
DLQ_ARN=$(awslocal sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names QueueArn \
  --region "$REGION" --query "Attributes.QueueArn" --output text)

if awslocal sqs get-queue-url --queue-name "$QUEUE_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "queue $QUEUE_NAME already exists, skipping"
  QUEUE_URL=$(awslocal sqs get-queue-url --queue-name "$QUEUE_NAME" --region "$REGION" --query QueueUrl --output text)
else
  ATTRS=$(python3 - "$DLQ_ARN" "$VISIBILITY_TIMEOUT" "$MAX_RECEIVE_COUNT" <<'PY'
import json
import sys

dlq_arn, visibility_timeout, max_receive_count = sys.argv[1:4]
print(json.dumps({
    "VisibilityTimeout": visibility_timeout,
    "RedrivePolicy": json.dumps({
        "deadLetterTargetArn": dlq_arn,
        "maxReceiveCount": max_receive_count,
    }),
}))
PY
)
  QUEUE_URL=$(awslocal sqs create-queue --queue-name "$QUEUE_NAME" --region "$REGION" \
    --attributes "$ATTRS" --query QueueUrl --output text)
fi
QUEUE_ARN=$(awslocal sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names QueueArn \
  --region "$REGION" --query "Attributes.QueueArn" --output text)

# S3 -> SQS event notification: any object created under uploads/ (the
# presigned POST's key prefix — see app/episodes/service.py) sends an event
# straight to the queue. No SNS fan-out in between — mirrors
# pipeline_stack.py's add_event_notification() wiring for AWS.
NOTIFICATION_CONFIG=$(python3 - "$QUEUE_ARN" <<'PY'
import json
import sys

queue_arn = sys.argv[1]
print(json.dumps({
    "QueueConfigurations": [
        {
            "QueueArn": queue_arn,
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {
                "Key": {"FilterRules": [{"Name": "prefix", "Value": "uploads/"}]}
            },
        }
    ]
}))
PY
)
awslocal s3api put-bucket-notification-configuration --bucket "$BUCKET_NAME" \
  --notification-configuration "$NOTIFICATION_CONFIG" --region "$REGION"

echo "init done"
