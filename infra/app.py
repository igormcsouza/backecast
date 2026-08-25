#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack
from stacks.pipeline_stack import PipelineStack

app = cdk.App()

stage = app.node.try_get_context("stage") or "dev"
ctx = app.node.try_get_context(stage)

# Phase 9: PR preview stages (`pr-<number>`, one per open PR — see
# .github/workflows/deploy-preview.yml) can't have a hand-authored entry in
# cdk.json's `context` block the way `dev`/`prod` do — nobody edits this
# file every time a PR is opened. Any stage matching that pattern falls
# back to `dev`'s region instead: same promotion mechanism (`-c stage=...`
# selects a stack-name prefix and a region), just without requiring a
# static context entry per PR number. Anything else unrecognized is a
# real mistake (a typo'd `-c stage=`), not a case to silently paper over.
if ctx is None:
    if stage.startswith("pr-"):
        ctx = {"region": app.node.try_get_context("dev")["region"]}
    else:
        raise ValueError(
            f"Unknown stage {stage!r} — add it to infra/cdk.json's `context` "
            "block (like `dev`/`prod`), or use a `pr-<number>` stage name "
            "for an ephemeral PR preview environment."
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
