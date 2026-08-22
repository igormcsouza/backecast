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

echo "init done — queue creation added in Phase 4"
