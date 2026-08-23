#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.api_stack import ApiStack
from stacks.ci_stack import CiStack
from stacks.data_stack import DataStack
from stacks.pipeline_stack import PipelineStack

app = cdk.App()

stage = app.node.try_get_context("stage") or "dev"
ctx = app.node.try_get_context(stage)
env = cdk.Environment(account=app.node.try_get_context("account"), region=ctx["region"])

data_stack = DataStack(app, f"Backecast-{stage}-Data", stage=stage, env=env)
ApiStack(
    app,
    f"Backecast-{stage}-Api",
    stage=stage,
    table=data_stack.table,
    bucket=data_stack.media_bucket,
    admin_key_param=data_stack.admin_key_param,
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

# Account-wide, not per-stage (see ci_stack.py's docstring) — instantiated
# once regardless of which `stage` context this synth ran with. Not part
# of deploy.yml's automated `cdk deploy` (Phase 8): a workflow can't grant
# itself the AWS trust it's about to be scoped by, so this one stack is a
# one-time manual bootstrap for Igor. See SESSIONS.md for the exact steps.
CiStack(
    app,
    "Backecast-Ci",
    github_repo="igormcsouza/backecast",
    github_branch="main",
    env=env,
)

app.synth()
