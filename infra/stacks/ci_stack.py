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
also why `deploy.yml`'s `deploy-backend` job triggers on a `workflow_run`
gated on `ci.yml` completing on `main` (not `pull_request`, and not a bare
`push` — see that file's own header comment for why it's `workflow_run`
specifically) — only that path ever produces a token whose `sub` claim
resolves to `refs/heads/main`, the only ref this role will accept.

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

Phase 9 — the dev -> prod promotion pattern, and PR previews
==============================================================

**`prod`.** Dev auto-deploys on every push to `main` (deploy.yml,
`workflow_run` off CI) because a bad dev deploy is cheap: nobody's using
it, and the next merge fixes it forward. Prod does not get that same
trigger — a `prod` deploy has to be a *deliberate* human act (a version
tag, `git push origin vX.Y.Z`, or a manual `workflow_dispatch` with a
confirmation input — see deploy-prod.yml), never an automatic side effect
of merging a PR. The mechanism for that: `GithubActionsDeployRole`'s trust
policy below now accepts a *second* `sub` claim shape,
`repo:<owner>/<repo>:ref:refs/tags/v*`, alongside the existing
`refs/heads/main` — so the exact same role (same permissions, same
identity) can be assumed by a tag-push-triggered workflow run, without
widening what that role is allowed to *do*. `refs/heads/main` still deploys
dev; a `v*` tag (or manual dispatch, which runs on whatever ref triggered
it — always `main` in practice, so it presents the *same* `refs/heads/main`
claim) deploys prod. Nothing here lets a non-`main`, non-tag ref in on this
trust — a feature-branch push still gets AccessDenied at STS, same as
before this phase.

**PR previews are a different trust shape, and get their own role.** The
easy-but-wrong move would have been to widen `GithubActionsDeployRole`'s
trust policy a *third* time to also accept a `pull_request`-event `sub`
claim (`repo:<owner>/<repo>:pull_request` — note: no PR number or branch
in that claim; GitHub's OIDC token can't distinguish *which* PR triggered
it, only that *some* pull_request event did). That single role would then
be assumable by every open PR against this repo, which means every PR
author effectively gets a path to the same credentials that deploy prod —
a much bigger blast radius than "can deploy a throwaway `pr-<number>`
stack." Instead, `GithubActionsPreviewDeployRole` (below) is a *separate*
role: its trust policy accepts only the `pull_request` claim (never
`refs/heads/main` or `refs/tags/v*`), so a PR workflow run can never
present a token this role trusts *and* also assume the prod/dev role, and
vice versa — a leaked preview credential can't touch dev or prod's trust
boundary, and a leaked deploy credential was never reachable from a PR run
in the first place. It still has to go through the same
`AssumeCdkBootstrapRoles` permission shape as the main role (see below),
because that's genuinely all `cdk deploy`/`cdk destroy` need in this
account — the isolation this buys is entirely at the *trust* layer (who
can assume the role), not at the downstream IAM-permission layer.

**Being honest about the limit of that isolation:** `cdk bootstrap`'s
default `cfn-exec` role (the one CloudFormation itself assumes to actually
create/update/delete resources) is broad — by default it's close to
account-admin, because CDK's bootstrap is designed for a single trusted
deployer, not multi-tenant isolation between "prod deploy" and "PR
preview deploy." Both `GithubActionsDeployRole` and
`GithubActionsPreviewDeployRole` ultimately assume *the same* bootstrap
roles, so a compromised preview role is not actually IAM-fenced away from
touching, say, the `prod` stack's resources — nothing at the AWS API layer
stops a `cdk deploy Backecast-prod-Data` call made with preview
credentials from succeeding. The real defenses against that are upstream
of IAM entirely, layered on purpose (defense in depth, not one silver
bullet): (1) GitHub does not hand a `pull_request`-triggered run from a
*fork* an OIDC token or repo secrets at all, by platform default — a
malicious fork PR has no token to present in the first place; (2)
deploy-preview.yml's job-level `if:` gate re-checks
`github.event.pull_request.head.repo.full_name == github.repository`
explicitly, as belt-and-suspenders in case that platform default is ever
misconfigured or changes; (3) the preview workflow itself only ever calls
`cdk deploy`/`cdk destroy` with `Backecast-pr-<number>-*` stack names,
literally never typing `dev`/`prod` anywhere in that job. A genuinely
tenant-isolated setup would additionally attach a permissions-boundary
policy to the bootstrap roles restricting them to `Backecast-pr-*`
resources — that requires a customized `cdk bootstrap` (not the default
one already run for this account) and is out of scope for this phase;
noted here, and in SESSIONS.md, as real follow-on hardening rather than
glossed over.
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
    output into the repo's GitHub Actions variables as `AWS_DEPLOY_ROLE_ARN`
    (and `GithubActionsPreviewDeployRoleArn` as `AWS_PREVIEW_ROLE_ARN`).
    Every push to `main` after that bootstraps itself automatically; a `v*`
    tag push or manual dispatch deploys prod; an open, same-repo PR gets a
    preview stack. See the module docstring's "Phase 9" section for why
    this is two roles, not a widened single role.
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
                    # StringLike (not StringEquals) matters for real now:
                    # `refs/tags/v*` has an actual wildcard. Two accepted
                    # `sub` shapes — `refs/heads/<branch>` (dev, every push
                    # to main) and `refs/tags/v*` (prod, a deliberate
                    # version-tag push or `workflow_dispatch` running off
                    # main — see the module docstring's "Phase 9" section
                    # for why this is a widened condition on the *same*
                    # role rather than a new one, unlike the PR-preview
                    # case below). A feature-branch push, or any ref that
                    # matches neither pattern, still gets AccessDenied.
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": [
                            f"repo:{github_repo}:ref:refs/heads/{github_branch}",
                            f"repo:{github_repo}:ref:refs/tags/v*",
                        ],
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

        # Phase 9 — PR preview deploys. A *separate* role from
        # `github_actions_deploy_role` on purpose: see the module
        # docstring's "Phase 9" section for the full reasoning (short
        # version — a `pull_request` OIDC claim can't identify *which* PR
        # triggered it, so trusting it on the same role that deploys prod
        # would let any open PR reach prod-capable credentials; a
        # dedicated role keeps that trust boundary separate even though
        # both roles still bottom out at the same `cdk bootstrap` roles —
        # see the docstring's honest note on where that isolation ends).
        github_actions_preview_role = iam.Role(
            self,
            "GithubActionsPreviewDeployRole",
            role_name="backecast-github-actions-preview",
            description=(
                "Assumed by GitHub Actions (OIDC) to deploy/destroy "
                f"ephemeral `Backecast-pr-<number>-*` stacks for {github_repo} "
                "pull requests. Separate from the main deploy role — see "
                "ci_stack.py's module docstring."
            ),
            assumed_by=iam.FederatedPrincipal(
                github_oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        # The `pull_request` event's `sub` claim shape —
                        # note it carries no PR number or branch name, only
                        # "some pull_request event fired in this repo".
                        # That's exactly why this role is scoped no further
                        # than "PR previews in general" and why
                        # deploy-preview.yml's own job-level `if:` gate
                        # (fork check) and stack-name discipline are load-
                        # bearing, not decorative — see the docstring.
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{github_repo}:pull_request"
                        ),
                    },
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
            # IAM's own floor is 1h (`max_session_duration` can't go lower
            # — AWS rejects anything under 3600s), so this can't be made
            # any tighter than the main deploy role's session length. The
            # narrowing for PR previews happens at the trust-policy layer
            # instead (see above and the module docstring), not here.
            max_session_duration=Duration.hours(1),
        )
        github_actions_preview_role.add_to_policy(
            iam.PolicyStatement(
                sid="AssumeCdkBootstrapRoles",
                effect=iam.Effect.ALLOW,
                actions=["sts:AssumeRole"],
                # Same bootstrap-role pattern as the main deploy role —
                # see this file's module docstring for why the isolation
                # PR previews get is at the *trust* layer (this role vs.
                # the main one), not a stack-name-scoped IAM permission
                # (the default `cdk bootstrap` roles don't support that
                # without a custom permissions boundary, which is out of
                # scope for this phase).
                resources=[bootstrap_role_pattern],
            )
        )

        CfnOutput(
            self,
            "GithubActionsPreviewDeployRoleArn",
            value=github_actions_preview_role.role_arn,
            description=(
                "Paste this into the repo's GitHub Actions variables as "
                "AWS_PREVIEW_ROLE_ARN — used by deploy-preview.yml for "
                "ephemeral PR preview stacks. See SESSIONS.md."
            ),
        )
