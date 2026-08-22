import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.data_stack import DataStack


def synth_template() -> Template:
    app = cdk.App()
    stack = DataStack(app, "TestStack", stage="dev")
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


def test_dev_buckets_are_destroyable():
    template = synth_template()
    template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Delete"})


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


def test_creates_admin_key_ssm_parameter():
    template = synth_template()
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {"Name": "/backecast/dev/admin-key"},
    )


def test_creates_openai_and_llm_api_key_ssm_parameters():
    # Phase 5: two more placeholder secrets, same pattern as the admin key —
    # Igor sets the real values post-deploy, never committed here.
    template = synth_template()
    template.resource_count_is("AWS::SSM::Parameter", 3)
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {"Name": "/backecast/dev/openai-api-key"},
    )
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {"Name": "/backecast/dev/llm-api-key"},
    )
