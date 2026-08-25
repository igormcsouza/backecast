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

        # `dev` and PR preview stages (`pr-<number>`, Phase 9) are both
        # throwaway: dev gets wiped and redeployed on every merge to `main`,
        # and a preview stack is `cdk destroy`'d the moment its PR closes
        # (see .github/workflows/deploy-preview.yml). Both need
        # `RemovalPolicy.DESTROY` + `auto_delete_objects=True` so teardown
        # actually succeeds unattended — RETAIN (the default for anything
        # else, i.e. `prod`) would leave an orphaned bucket/table behind on
        # every `cdk destroy` and, worse, a non-empty S3 bucket makes
        # CloudFormation delete fail outright, hanging the preview teardown
        # job. `prod` deliberately keeps RETAIN: losing production data
        # because someone fat-fingered a stack deletion is a much worse
        # outcome than a manual cleanup later.
        is_ephemeral = stage == "dev" or stage.startswith("pr-")
        removal_policy = RemovalPolicy.DESTROY if is_ephemeral else RemovalPolicy.RETAIN

        self.media_bucket = s3.Bucket(
            self,
            "MediaBucket",
            bucket_name=f"backecast-media-{stage}-{self.account}",
            removal_policy=removal_policy,
            auto_delete_objects=is_ephemeral,
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

        self.table = dynamodb.Table(
            self,
            "Table",
            table_name=f"backecast-{stage}",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
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

        # Two placeholder secrets for Phase 5's worker:
        # the OpenAI API key (transcription, worker/transcription.py) and
        # the chat-model provider's API key (metadata generation,
        # worker/metadata.py). Two separate parameters — not one shared
        # "LLM key" — because the provider-swap seam (settings.llm_model,
        # e.g. "openai:gpt-4o-mini" vs "anthropic:claude-3-5-haiku-latest")
        # means the metadata chain's key may belong to a different provider
        # than the transcription key entirely. Igor sets the real values
        # post-deploy, same as the admin key above — this task never reads
        # or fabricates a real key.
        self.openai_api_key_param = ssm.StringParameter(
            self,
            "OpenAiApiKeyParam",
            parameter_name=f"/backecast/{stage}/openai-api-key",
            string_value="changeme-placeholder",
        )
        self.llm_api_key_param = ssm.StringParameter(
            self,
            "LlmApiKeyParam",
            parameter_name=f"/backecast/{stage}/llm-api-key",
            string_value="changeme-placeholder",
        )
