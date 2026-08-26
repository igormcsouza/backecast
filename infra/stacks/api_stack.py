from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as apigwv2_integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk.aws_lambda_python_alpha import BundlingOptions, PythonFunction
from constructs import Construct

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        table: dynamodb.Table,
        bucket: s3.Bucket,
        user_pool_id: str,
        user_pool_client_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        api_function = PythonFunction(
            self,
            "ApiFunction",
            entry=str(BACKEND_DIR),
            index="app/main.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            bundling=BundlingOptions(
                asset_excludes=[
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "tests",
                    ".git",
                    ".dockerignore",
                    "Dockerfile",
                ],
            ),
            environment={
                "STAGE": stage,
                "TABLE_NAME": table.table_name,
                "MEDIA_BUCKET_NAME": bucket.bucket_name,
                "COGNITO_USER_POOL_ID": user_pool_id,
                "COGNITO_CLIENT_ID": user_pool_client_id,
                "COGNITO_REGION": self.region,
            },
            timeout=Duration.seconds(10),
            memory_size=256,
        )
        # read_write (not read-only anymore): creating an episode is a
        # PutItem. Coarser than strictly needed (also grants Update/Delete) —
        # a tighter `table.grant(api_function, "dynamodb:PutItem", ...)`
        # is a fine Phase-9 hardening exercise, not worth it here.
        table.grant_read_write_data(api_function)

        # The presigned POST's signature is derived from the Lambda's own
        # IAM credentials, even though the browser uploads directly to S3 —
        # without PutObject on the role, S3 rejects the signature at upload
        # time even though the Lambda itself never touches the bytes.
        bucket.grant_put(api_function)

        # Same reasoning for playback: the presigned GET the public episode
        # route hands back (app/episodes/service.py's `_with_audio_url`) is
        # also just a signature over the Lambda's own credentials — without
        # GetObject on the role, every presigned URL it mints 403s the
        # moment a browser actually requests it, even though the signature
        # itself looks well-formed. Scoped to uploads/* and transcripts/*
        # (the only prefixes the API ever reads back) rather than the whole
        # bucket.
        bucket.grant_read(api_function, objects_key_pattern="uploads/*")
        bucket.grant_read(api_function, objects_key_pattern="transcripts/*")

        http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name=f"backecast-{stage}",
            default_integration=apigwv2_integrations.HttpLambdaIntegration(
                "ApiIntegration", api_function
            ),
        )

        CfnOutput(self, "ApiUrl", value=http_api.url)
