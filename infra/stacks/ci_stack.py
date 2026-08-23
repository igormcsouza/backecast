"""GitHub Actions -> AWS trust, via OIDC. No long-lived AWS keys in GitHub.

The problem this replaces: the "obvious" way to let a GitHub Actions
workflow call `cdk deploy` is to create an IAM user, mint an access key
pair, and paste `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` into the repo's
GitHub secrets. That key pair is long-lived (valid until someone manually
rotates or deletes it), works from anywhere on the internet if it leaks
(a fork's PR, a compromised Action, a leaked log line), and grants
whatever permissions were attached to it forever.

OIDC federation removes the secret entirely. GitHub's own token service
(`token.actions.githubusercontent.com`) signs a short-lived JSON Web Token
for *every* workflow run and injects it into the job. AWS STS is taught to
trust that issuer as an "OpenID Connect provider" (`GithubOidcProvider`
below) and, when a workflow calls `sts:AssumeRoleWithWebIdentity` with that
token, exchanges it for temporary AWS credentials (~1h, `max_session_duration`
below) scoped to whatever IAM role's trust policy accepted the token. No
credential exists before the workflow starts, and none is stored anywhere
after it ends — there is nothing to leak and nothing to rotate.

The trust is not "any GitHub Actions run, anywhere": the role's trust
policy (`GithubActionsDeployRole` below) checks the JWT's `sub` claim
against `repo:<owner>/<repo>:ref:refs/heads/<branch>` — literally this
repo, literally the `main` branch. A workflow run in a different repo, or
a PR branch in *this* repo, presents a `sub` claim that does not match and
gets an "AccessDenied" from STS before any AWS API call happens. This is
also why `deploy.yml` triggers on `push: branches: [main]` rather than
`pull_request` — only a push to `main` ever produces a token this role
will accept in the first place.

Least privilege: `GithubActionsDeployRole` is granted exactly one action —
`sts:AssumeRole` — and only onto this account's own CDK bootstrap roles
(`cdk-<qualifier>-*-role-<account>-<region>`, created once by `cdk
bootstrap` and already scoped by AWS to what CDK deploys actually need:
CloudFormation execution, S3/ECR asset publishing, environment lookups).
That is the standard, AWS-documented shape for a CDK-deploying CI role,
and it is deliberately *not* `AdministratorAccess` (or even a hand-rolled
policy re-granting Lambda/DynamoDB/S3/etc. permissions directly) — the
bootstrap roles already carry the real permissions and are reviewable/
auditable on their own, so this role's blast radius if it were ever
misused is bounded by whatever `cdk bootstrap` itself grants, not by
whatever the author of this file remembered to list.
"""

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

# The default qualifier `cdk bootstrap` uses when none is configured
# (infra/cdk.json sets none) — see the bootstrap role ARN pattern below.
DEFAULT_CDK_QUALIFIER = "hnb659fds"


class CiStack(Stack):
    """OIDC provider + deploy role for GitHub Actions. Account-wide, not
    per-stage: an IAM OIDC provider is a single account-level resource (AWS
    rejects registering the same provider URL twice in one account), so
    unlike DataStack/ApiStack/PipelineStack this stack is instantiated once
    in app.py, not once per `stage` context value.

    Not deployed by this session (see SESSIONS.md) — Igor deploys it once,
    by hand, with his own AWS credentials, and pastes the `GithubActionsDeployRoleArn`
    output into the repo's GitHub Actions variables as `AWS_DEPLOY_ROLE_ARN`.
    Every push to `main` after that bootstraps itself automatically.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        github_repo: str,
        github_branch: str = "main",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        github_oidc_provider = iam.OpenIdConnectProvider(
            self,
            "GithubOidcProvider",
            url="https://token.actions.githubusercontent.com",
            # The only audience GitHub's own `configure-aws-credentials`
            # action ever requests — the value baked into deploy.yml's
            # `aws-actions/configure-aws-credentials` step has to match
            # this exactly, or STS rejects the token at the audience check
            # before it even looks at the trust policy conditions below.
            client_ids=["sts.amazonaws.com"],
            # No `thumbprints=` passed: CDK resolves the current provider
            # thumbprint itself at deploy time rather than a value hardcoded
            # here going stale if GitHub ever rotates its TLS certificate.
        )

        github_actions_deploy_role = iam.Role(
            self,
            "GithubActionsDeployRole",
            role_name="backecast-github-actions-deploy",
            description=(
                "Assumed by GitHub Actions (OIDC) to run `cdk deploy` for "
                f"{github_repo}@{github_branch}. No long-lived AWS keys "
                "involved — see ci_stack.py's module docstring."
            ),
            assumed_by=iam.FederatedPrincipal(
                github_oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    },
                    # StringLike (not StringEquals) is irrelevant here since
                    # there's no wildcard in the value — used anyway because
                    # it's the condition operator AWS's own OIDC docs use
                    # for the `sub` claim, and it composes cleanly if this
                    # is ever loosened to `refs/heads/*` for a multi-branch
                    # deploy setup later.
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{github_repo}:ref:refs/heads/{github_branch}"
                        ),
                    },
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
            # Matches deploy.yml's job runtime, which never needs the
            # credentials past a single `cdk deploy --all` invocation —
            # capping the session length bounds how long a leaked/cached
            # token (e.g. in an Actions log, however unlikely) stays useful.
            max_session_duration=Duration.hours(1),
        )

        # `cdk bootstrap` (run once per account/region, by Igor, outside
        # this stack) creates five roles under this naming pattern, each
        # already scoped to one part of the deploy: file-publishing (S3
        # asset uploads), image-publishing (ECR, for PipelineStack's
        # DockerImageFunction), deploy (the role `cdk deploy` itself
        # assumes to call CloudFormation), cfn-exec (the role
        # CloudFormation uses to actually create/update resources), and
        # lookup (read-only, for context queries like AZ lookups). Granting
        # `sts:AssumeRole` on all five — rather than trying to guess which
        # one `cdk deploy` needs at every step — is the documented AWS
        # pattern; the real permission boundary lives in those bootstrap
        # roles' own policies, not here.
        bootstrap_role_pattern = self.format_arn(
            service="iam",
            region="",  # IAM ARNs are global — no region component.
            resource="role",
            resource_name=f"cdk-{DEFAULT_CDK_QUALIFIER}-*-role-{self.account}-{self.region}",
        )
        github_actions_deploy_role.add_to_policy(
            iam.PolicyStatement(
                sid="AssumeCdkBootstrapRoles",
                effect=iam.Effect.ALLOW,
                actions=["sts:AssumeRole"],
                resources=[bootstrap_role_pattern],
            )
        )

        CfnOutput(
            self,
            "GithubActionsDeployRoleArn",
            value=github_actions_deploy_role.role_arn,
            description=(
                "Paste this into the repo's GitHub Actions variables as "
                "AWS_DEPLOY_ROLE_ARN — see SESSIONS.md for the full "
                "bootstrap sequence."
            ),
        )
