#!/usr/bin/env python3
import aws_cdk as cdk
from aws_cdk import Tags

from stacks.api_stack import ApiStack
from stacks.data_stack import DataStack
from stacks.pipeline_stack import PipelineStack
from stacks.web_stack import WebCertStack, WebStack

app = cdk.App()

stage = app.node.try_get_context("stage") or "prod"
ctx = app.node.try_get_context(stage)

# Only one real stage: `prod` (the live public site). There is no `dev`
# anymore — it was a separate always-on stage that just duplicated `prod`'s
# cost. Ephemeral per-PR preview stacks were dropped too (see #19) — CI's
# `deploy-check` job (`cdk diff` against `prod`) now covers "would this
# deploy" without creating a parallel environment per PR.
if ctx is None:
    raise ValueError(
        f"Unknown stage {stage!r} — add it to infra/cdk.json's `context` block (like `prod`)."
    )

env = cdk.Environment(account=app.node.try_get_context("account"), region=ctx["region"])

data_stack = DataStack(app, f"Backecast-{stage}-Data", stage=stage, env=env)
# Admin sign-in is Citadel (the shared SSO pool, owned by the `citadel` repo; this app is registered in its
# config/apps.json). Nothing here creates a user pool any more.
citadel = app.node.try_get_context("citadel")
ApiStack(
    app,
    f"Backecast-{stage}-Api",
    stage=stage,
    table=data_stack.table,
    bucket=data_stack.media_bucket,
    user_pool_id=citadel["user_pool_id"],
    user_pool_client_id=citadel["client_id"],
    env=env,
)
web = ctx["web"]
web_cert = WebCertStack(
    app,
    f"Backecast-{stage}-WebCert",
    **web,
    env=cdk.Environment(account=env.account, region="us-east-1"),
    cross_region_references=True,
)
WebStack(
    app,
    f"Backecast-{stage}-Web",
    **web,
    cert=web_cert.cert,
    env=env,
    cross_region_references=True,
)
PipelineStack(
    app,
    f"Backecast-{stage}-Pipeline",
    stage=stage,
    table=data_stack.table,
    bucket=data_stack.media_bucket,
    openai_api_key_param=data_stack.openai_api_key_param,
    llm_api_key_param=data_stack.llm_api_key_param,
    env=env,
    # Worker Docker image goes to a dedicated, pre-existing ECR repo (created
    # by hand, with a lifecycle policy) instead of the shared CDK bootstrap one.
    synthesizer=cdk.DefaultStackSynthesizer(
        image_assets_repository_name="backecast-assets"
    ),
)

# Cost allocation tag — splits the AWS bill per project.
Tags.of(app).add("project", "backecast")

app.synth()
