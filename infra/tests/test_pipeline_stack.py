import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.data_stack import DataStack
from stacks.pipeline_stack import PipelineStack


def synth_template() -> Template:
    app = cdk.App()
    data_stack = DataStack(app, "TestDataStack", stage="dev")
    pipeline_stack = PipelineStack(
        app,
        "TestPipelineStack",
        stage="dev",
        table=data_stack.table,
        bucket=data_stack.media_bucket,
    )
    return Template.from_stack(pipeline_stack)


def test_creates_main_queue_and_dlq():
    synth_template().resource_count_is("AWS::SQS::Queue", 2)


def test_main_queue_has_redrive_policy_to_dlq_with_max_receive_count_3():
    template = synth_template()
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "RedrivePolicy": Match.object_like({"maxReceiveCount": 3}),
        },
    )


def test_main_queue_visibility_timeout_is_six_times_worker_timeout():
    template = synth_template()
    # WORKER_TIMEOUT is 30s in pipeline_stack.py; visibility must be 6x that.
    template.has_resource_properties(
        "AWS::SQS::Queue",
        Match.object_like({"VisibilityTimeout": 180}),
    )


def test_creates_worker_lambda_with_python312_runtime():
    # Not a resource_count_is(1): the S3 bucket notification wiring also
    # provisions its own tiny custom-resource Lambda (the
    # BucketNotificationsHandler) alongside the worker function — this
    # asserts the *worker's* shape specifically, ignoring how many other
    # Lambdas CDK's L2 constructs add behind the scenes.
    template = synth_template()
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Runtime": "python3.12",
            "Handler": "worker.handler.handler",
        },
    )


def test_worker_lambda_can_read_and_write_the_table():
    template = synth_template()
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": Match.array_with(
                                    ["dynamodb:GetItem", "dynamodb:PutItem"]
                                ),
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_event_source_mapping_enables_report_batch_item_failures():
    template = synth_template()
    template.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {
            "BatchSize": 5,
            "FunctionResponseTypes": ["ReportBatchItemFailures"],
        },
    )


def test_creates_s3_bucket_notification_to_the_queue():
    template = synth_template()
    # add_event_notification() creates a Custom::S3BucketNotifications
    # resource (a Lambda-backed custom resource) — asserting its presence
    # confirms the S3 -> SQS wiring was actually configured, without
    # over-specifying the custom resource's internal shape.
    template.resource_count_is("Custom::S3BucketNotifications", 1)
