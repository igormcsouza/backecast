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

ADMIN_KEY_PARAM="/backecast/dev/admin-key"

# Fixed, known value for local/CI only — integration tests hardcode it.
# Real AWS gets its value set manually via `aws ssm put-parameter --overwrite`,
# never committed.
if awslocal ssm get-parameter --name "$ADMIN_KEY_PARAM" --region "$REGION" >/dev/null 2>&1; then
  echo "param $ADMIN_KEY_PARAM already exists, skipping"
else
  awslocal ssm put-parameter --name "$ADMIN_KEY_PARAM" --type String \
    --value "local-dev-admin-key" --region "$REGION"
fi

DLQ_NAME="backecast-dev-media-dlq"
QUEUE_NAME="backecast-dev-media-queue"

# Visibility timeout here must match infra/stacks/pipeline_stack.py's
# VISIBILITY_TIMEOUT (~6x the worker Lambda's own timeout) — see that file
# for why 6x. Kept as a literal here rather than derived because this script
# has no Python/CDK context to import it from; if you change one, change
# the other. maxReceiveCount likewise mirrors MAX_RECEIVE_COUNT there.
VISIBILITY_TIMEOUT="180"
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
