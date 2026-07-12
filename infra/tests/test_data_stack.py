import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.data_stack import DataStack


def synth_template() -> Template:
    app = cdk.App()
    stack = DataStack(app, "TestStack", stage="dev")
    return Template.from_stack(stack)


def test_creates_two_buckets():
    synth_template().resource_count_is("AWS::S3::Bucket", 2)


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
