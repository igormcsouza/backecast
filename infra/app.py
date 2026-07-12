#!/usr/bin/env python3
import aws_cdk as cdk

app = cdk.App()

stage = app.node.try_get_context("stage") or "dev"
ctx = app.node.try_get_context(stage)
env = cdk.Environment(account=app.node.try_get_context("account"), region=ctx["region"])

# Placeholder stack proving the CDK toolchain works end-to-end. Phase 1
# replaces this with data_stack/api_stack/pipeline_stack/frontend_stack.
cdk.Stack(app, f"Backecast-{stage}-Placeholder", env=env)

app.synth()
