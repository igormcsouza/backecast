#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack
from stacks.pipeline_stack import PipelineStack

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
auth_stack = AuthStack(app, f"Backecast-{stage}-Auth", stage=stage, env=env)
ApiStack(
    app,
    f"Backecast-{stage}-Api",
    stage=stage,
    table=data_stack.table,
    bucket=data_stack.media_bucket,
    user_pool_id=auth_stack.user_pool.user_pool_id,
    user_pool_client_id=auth_stack.user_pool_client.user_pool_client_id,
    env=env,
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
)

app.synth()
