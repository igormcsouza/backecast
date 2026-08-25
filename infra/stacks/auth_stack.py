"""Cognito User Pool backing admin auth.

Replaces the old shared `X-Admin-Key` (a single secret string in SSM,
checked with `secrets.compare_digest`) with a real Cognito User Pool: the
admin logs in with a username and password, the frontend exchanges those
for a JWT access token via Cognito's `InitiateAuth` (USER_PASSWORD_AUTH)
API, and the backend verifies that token's signature against the pool's
public JWKS on every admin request — see backend/app/core/auth.py.

Self-sign-up is deliberately disabled (`self_sign_up_enabled=False`) and
this stack never creates a user itself: Igor creates the single admin user
by hand in the Cognito console and sets a *permanent* password there (not
a temporary one), so the frontend never has to handle Cognito's
NEW_PASSWORD_REQUIRED challenge. There is no public sign-up route anywhere
in this app, by design — see manual.md.

Username sign-in, not email: `sign_in_aliases=SignInAliases(username=True,
email=False)` — Igor's call, the admin login page takes a plain username,
not an email address.
"""

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from constructs import Construct


class AuthStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, stage: str, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Same ephemeral-stage reasoning as DataStack (dev and PR previews
        # are throwaway and must tear down cleanly; prod data must not
        # vanish on an accidental `cdk destroy`) — a User Pool holding a
        # real admin identity deserves the same RETAIN-by-default treatment
        # as the DynamoDB table.
        is_ephemeral = stage == "dev" or stage.startswith("pr-")
        removal_policy = RemovalPolicy.DESTROY if is_ephemeral else RemovalPolicy.RETAIN

        self.user_pool = cognito.UserPool(
            self,
            "AdminUserPool",
            user_pool_name=f"backecast-{stage}-admin",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True, email=False),
            account_recovery=cognito.AccountRecovery.NONE,
            removal_policy=removal_policy,
        )

        # No client secret: `InitiateAuth` is called directly from the
        # browser (a public client), and a "secret" baked into client-side
        # JS isn't a secret — Cognito's own public-client pattern.
        self.user_pool_client = cognito.UserPoolClient(
            self,
            "AdminUserPoolClient",
            user_pool=self.user_pool,
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_password=True),
        )

        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(
            self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id
        )
