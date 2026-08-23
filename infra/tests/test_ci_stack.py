import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.ci_stack import CiStack


def synth_template() -> Template:
    app = cdk.App()
    ci_stack = CiStack(
        app,
        "TestCiStack",
        github_repo="igormcsouza/backecast",
        github_branch="main",
        env=cdk.Environment(account="123456789012", region="sa-east-1"),
    )
    return Template.from_stack(ci_stack)


def test_creates_exactly_one_github_oidc_provider():
    # The custom-resource-backed provider is what actually registers with
    # IAM; asserting on the custom resource type (not a Lambda count, which
    # the CDK-internal handler also contributes to) pins down "exactly one
    # provider for GitHub" without coupling to CDK's own implementation
    # details of how it's provisioned.
    synth_template().resource_count_is("Custom::AWSCDKOpenIdConnectProvider", 1)


def test_oidc_provider_trusts_github_actions_issuer():
    template = synth_template()
    template.has_resource_properties(
        "Custom::AWSCDKOpenIdConnectProvider",
        {
            "Url": "https://token.actions.githubusercontent.com",
            "ClientIDList": ["sts.amazonaws.com"],
        },
    )


def test_deploy_role_trust_policy_scoped_to_repo_and_branch():
    # This is the trust boundary the whole phase is about: only a workflow
    # run whose GitHub-issued JWT carries one of these exact `sub` claims
    # (this repo's `main` branch, for dev; or a `v*` tag on this repo, for
    # prod — Phase 9's promotion pattern, see ci_stack.py's module
    # docstring) can assume the role — not any other repo, not a feature
    # branch, and not a pull_request run against this same repo (that gets
    # its own, separate role — see the preview-role tests below).
    template = synth_template()
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": "backecast-github-actions-deploy",
            "AssumeRolePolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "sts:AssumeRoleWithWebIdentity",
                                "Effect": "Allow",
                                "Condition": {
                                    "StringEquals": {
                                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                    },
                                    "StringLike": {
                                        "token.actions.githubusercontent.com:sub": [
                                            "repo:igormcsouza/backecast:ref:refs/heads/main",
                                            "repo:igormcsouza/backecast:ref:refs/tags/v*",
                                        ],
                                    },
                                },
                            }
                        )
                    ]
                )
            },
        },
    )


def test_preview_role_trust_policy_scoped_to_pull_request_event_only():
    # The preview role's trust is deliberately *disjoint* from the main
    # deploy role's: it accepts the `pull_request` event's `sub` claim and
    # nothing ref-based, so a PR-triggered token can never satisfy the main
    # role's trust condition (and vice versa) — see ci_stack.py's module
    # docstring for why these are two roles, not one widened role.
    template = synth_template()
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": "backecast-github-actions-preview",
            "AssumeRolePolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "sts:AssumeRoleWithWebIdentity",
                                "Effect": "Allow",
                                "Condition": {
                                    "StringEquals": {
                                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                        "token.actions.githubusercontent.com:sub": "repo:igormcsouza/backecast:pull_request",
                                    },
                                },
                            }
                        )
                    ]
                )
            },
        },
    )


def test_preview_role_can_only_assume_this_accounts_cdk_bootstrap_roles():
    # Same least-privilege shape as the main deploy role: exactly
    # sts:AssumeRole, only onto this account's cdk bootstrap roles.
    template = synth_template()
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "sts:AssumeRole",
                                "Effect": "Allow",
                                "Resource": {
                                    "Fn::Join": [
                                        "",
                                        Match.array_with(
                                            [
                                                Match.string_like_regexp(
                                                    r":iam::123456789012:role/cdk-hnb659fds-\*-role-123456789012-sa-east-1"
                                                )
                                            ]
                                        ),
                                    ]
                                },
                            }
                        )
                    ]
                )
            },
            "Roles": Match.array_with(
                [{"Ref": Match.string_like_regexp("GithubActionsPreviewDeployRole")}]
            ),
        },
    )


def test_deploy_role_can_only_assume_this_accounts_cdk_bootstrap_roles():
    # Least privilege: no direct service permissions (Lambda/DynamoDB/S3/
    # etc.) are granted to this role at all — only sts:AssumeRole, and only
    # onto this account's own `cdk bootstrap` roles, never "*". The
    # resource is an Fn::Join (account/region are tokens, not literals, per
    # CLAUDE.md's "no hardcoded account ID" convention) — assert on the
    # literal fragment that carries the actual scoping instead of a plain
    # string match.
    template = synth_template()
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "sts:AssumeRole",
                                "Effect": "Allow",
                                "Resource": {
                                    "Fn::Join": [
                                        "",
                                        Match.array_with(
                                            [
                                                Match.string_like_regexp(
                                                    r":iam::123456789012:role/cdk-hnb659fds-\*-role-123456789012-sa-east-1"
                                                )
                                            ]
                                        ),
                                    ]
                                },
                            }
                        )
                    ]
                )
            }
        },
    )


def test_deploy_role_is_not_granted_administrator_access():
    template = synth_template()
    template.resource_count_is(
        "AWS::IAM::Role", 3
    )  # deploy role + preview role (Phase 9) + the CDK-internal custom
    # resource's own role
    policies = template.find_resources("AWS::IAM::Policy")
    for policy in policies.values():
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            assert statement["Action"] != "*"
            assert statement.get("Resource") != "*" or statement["Action"] not in (
                "*",
                ["*"],
            )
