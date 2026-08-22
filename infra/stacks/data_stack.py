from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_ssm as ssm
from constructs import Construct


class DataStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, stage: str, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dev_policy = RemovalPolicy.DESTROY if stage == "dev" else RemovalPolicy.RETAIN
        is_dev = stage == "dev"

        self.media_bucket = s3.Bucket(
            self,
            "MediaBucket",
            bucket_name=f"backecast-media-{stage}-{self.account}",
            removal_policy=dev_policy,
            auto_delete_objects=is_dev,
            cors=[
                s3.CorsRule(
                    allowed_methods=[
                        s3.HttpMethods.PUT,
                        s3.HttpMethods.POST,
                        s3.HttpMethods.GET,
                    ],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                )
            ],
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-incomplete-uploads",
                    abort_incomplete_multipart_upload_after=Duration.days(1),
                )
            ],
        )

        self.frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"backecast-frontend-{stage}-{self.account}",
            removal_policy=dev_policy,
            auto_delete_objects=is_dev,
        )

        self.table = dynamodb.Table(
            self,
            "Table",
            table_name=f"backecast-{stage}",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=dev_policy,
        )
        self.table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(
                name="GSI1PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="GSI1SK", type=dynamodb.AttributeType.STRING
            ),
        )

        # Placeholder value — the real secret is set manually post-deploy via
        # `aws ssm put-parameter --overwrite`, never committed. A plain
        # StringParameter (not SecureString) is used because CDK's L2
        # construct doesn't support SecureString directly; acceptable for a
        # single dev-only shared admin secret.
        self.admin_key_param = ssm.StringParameter(
            self,
            "AdminKeyParam",
            parameter_name=f"/backecast/{stage}/admin-key",
            string_value="changeme-placeholder",
        )
