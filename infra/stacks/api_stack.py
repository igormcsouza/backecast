from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as apigwv2_integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
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
            },
            timeout=Duration.seconds(10),
            memory_size=256,
        )
        table.grant_read_data(api_function)

        http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name=f"backecast-{stage}",
            default_integration=apigwv2_integrations.HttpLambdaIntegration(
                "ApiIntegration", api_function
            ),
        )

        CfnOutput(self, "ApiUrl", value=http_api.url)
