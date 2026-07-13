import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.api_stack import ApiStack
from stacks.data_stack import DataStack


def synth_template() -> Template:
    app = cdk.App()
    data_stack = DataStack(app, "TestDataStack", stage="dev")
    api_stack = ApiStack(app, "TestApiStack", stage="dev", table=data_stack.table)
    return Template.from_stack(api_stack)


def test_creates_one_lambda_function():
    synth_template().resource_count_is("AWS::Lambda::Function", 1)


def test_lambda_uses_python312_and_mangum_handler():
    template = synth_template()
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Runtime": "python3.12",
            "Handler": "app.main.handler",
        },
    )


def test_creates_http_api_with_proxy_integration():
    template = synth_template()
    template.resource_count_is("AWS::ApiGatewayV2::Api", 1)
    template.has_resource_properties(
        "AWS::ApiGatewayV2::Integration",
        {
            "IntegrationType": "AWS_PROXY",
            "PayloadFormatVersion": "2.0",
        },
    )


def test_lambda_can_read_the_table():
    template = synth_template()
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": [
                                    "dynamodb:BatchGetItem",
                                    "dynamodb:Query",
                                    "dynamodb:GetItem",
                                    "dynamodb:Scan",
                                    "dynamodb:ConditionCheckItem",
                                    "dynamodb:DescribeTable",
                                ],
                                "Effect": "Allow",
                            }
                        )
                    ]
                )
            }
        },
    )
