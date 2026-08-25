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
        openai_api_key_param=data_stack.openai_api_key_param,
        llm_api_key_param=data_stack.llm_api_key_param,
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
    # WORKER_TIMEOUT is 5 minutes (300s) in pipeline_stack.py — Phase 5's
    # callback to the Phase 4 6x rule: visibility must scale with it.
    template.has_resource_properties(
        "AWS::SQS::Queue",
        Match.object_like({"VisibilityTimeout": 1800}),
    )


def test_creates_worker_lambda_as_a_container_image_with_five_minute_timeout():
    # Phase 5: the worker ships as a container image (ffmpeg bundled in),
    # not a zip — PackageType=Image with no Handler/Runtime is exactly what
    # DockerImageFunction synthesizes to.
    template = synth_template()
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "PackageType": "Image",
            "Timeout": 300,
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


def test_worker_lambda_can_read_uploads_and_read_write_transcripts():
    # Scoped grants (objects_key_pattern), not a blanket grant_read_write on
    # the whole bucket — the worker only ever touches uploads/ (read) and
    # transcripts/ (read + write: `_advance_generating` reads back the
    # transcript a later stage of the same episode's state machine wrote
    # earlier — see pipeline_stack.py's comment on why this needs GetObject
    # too, not just PutObject).
    template = synth_template()
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": Match.array_with(["s3:GetObject*"]),
                                "Effect": "Allow",
                                "Resource": Match.any_value(),
                            }
                        ),
                        Match.object_like(
                            {
                                "Action": Match.array_with(["s3:GetObject*"]),
                                "Effect": "Allow",
                                "Resource": Match.any_value(),
                            }
                        ),
                        Match.object_like(
                            {
                                "Action": Match.array_with(["s3:PutObject"]),
                                "Effect": "Allow",
                            }
                        ),
                    ]
                )
            }
        },
    )


def test_worker_lambda_can_read_the_openai_and_llm_api_key_params():
    # SSM parameters themselves live in DataStack (see test_data_stack.py);
    # this asserts PipelineStack's own IAM policy grants GetParameter on
    # both — openai_api_key_param.grant_read() and
    # llm_api_key_param.grant_read() each add their own statement to the
    # worker role's single combined policy.
    template = synth_template()
    policies = template.find_resources("AWS::IAM::Policy")
    statements = [
        stmt
        for policy in policies.values()
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]
        if "ssm:GetParameter" in (stmt.get("Action") or [])
    ]
    # One statement per grant_read() call — openai key, llm key.
    assert len(statements) == 2


def test_event_source_mapping_enables_report_batch_item_failures():
    template = synth_template()
    template.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {
            "BatchSize": 1,
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
