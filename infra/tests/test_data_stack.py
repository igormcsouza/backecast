import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.data_stack import DataStack


def synth_template() -> Template:
    app = cdk.App()
    stack = DataStack(app, "TestStack", stage="prod")
    return Template.from_stack(stack)


def test_creates_one_bucket():
    # Frontend is served from GitHub Pages, not S3+CloudFront — only the
    # media bucket lives here.
    synth_template().resource_count_is("AWS::S3::Bucket", 1)


def test_table_has_composite_key_billing_mode_and_gsi():
    template = synth_template()
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                }
            ],
        },
    )


def test_pr_preview_buckets_and_tables_are_destroyable():
    # A `pr-<number>` stage is torn down (`cdk destroy`) the moment its PR
    # closes (deploy-preview.yml) — if this stayed on the RETAIN default,
    # the bucket (non-empty, since it holds uploaded media) would fail to
    # delete and hang that teardown job every time.
    app = cdk.App()
    stack = DataStack(app, "TestPreviewStack", stage="pr-999")
    template = Template.from_stack(stack)
    template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Delete"})
    template.has_resource("AWS::DynamoDB::Table", {"DeletionPolicy": "Delete"})


def test_prod_buckets_and_tables_are_retained():
    # The flip side: `prod` never gets a `pr-*` free pass — a `cdk
    # destroy` (accidental or deliberate) against prod should leave the
    # bucket/table behind rather than silently deleting real data.
    app = cdk.App()
    stack = DataStack(app, "TestProdStack", stage="prod")
    template = Template.from_stack(stack)
    template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Retain"})
    template.has_resource("AWS::DynamoDB::Table", {"DeletionPolicy": "Retain"})


def test_media_bucket_cors_allows_post():
    template = synth_template()
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "CorsConfiguration": {
                "CorsRules": Match.array_with(
                    [Match.object_like({"AllowedMethods": Match.array_with(["POST"])})]
                )
            }
        },
    )


def test_creates_openai_and_llm_api_key_ssm_parameters():
    # Igor sets the real values post-deploy, never committed here.
    template = synth_template()
    template.resource_count_is("AWS::SSM::Parameter", 2)
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {"Name": "/backecast/prod/openai-api-key"},
    )
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {"Name": "/backecast/prod/llm-api-key"},
    )
