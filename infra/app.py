#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.api_stack import ApiStack
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
    env=env,
)

app.synth()
