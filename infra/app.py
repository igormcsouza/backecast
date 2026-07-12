#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.data_stack import DataStack

app = cdk.App()

stage = app.node.try_get_context("stage") or "dev"
ctx = app.node.try_get_context(stage)
env = cdk.Environment(account=app.node.try_get_context("account"), region=ctx["region"])

DataStack(app, f"Backecast-{stage}-Data", stage=stage, env=env)

app.synth()
