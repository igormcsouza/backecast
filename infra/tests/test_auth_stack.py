import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.auth_stack import AuthStack


def synth_template(stage: str = "dev") -> Template:
    app = cdk.App()
    stack = AuthStack(app, "TestAuthStack", stage=stage)
    return Template.from_stack(stack)


def test_creates_one_user_pool_and_client():
    template = synth_template()
    template.resource_count_is("AWS::Cognito::UserPool", 1)
    template.resource_count_is("AWS::Cognito::UserPoolClient", 1)


def test_self_sign_up_is_disabled():
    template = synth_template()
    template.has_resource_properties(
        "AWS::Cognito::UserPool",
        {"AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True}},
    )


def test_client_has_no_secret_and_allows_user_password_auth():
    template = synth_template()
    template.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "GenerateSecret": False,
            "ExplicitAuthFlows": ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        },
    )


def test_dev_pool_is_destroyable():
    template = synth_template("dev")
    template.has_resource("AWS::Cognito::UserPool", {"DeletionPolicy": "Delete"})


def test_prod_pool_is_retained():
    template = synth_template("prod")
    template.has_resource("AWS::Cognito::UserPool", {"DeletionPolicy": "Retain"})
