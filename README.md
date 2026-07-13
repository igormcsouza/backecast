# README

Notes on local-environment options considered but not adopted (yet). Kept here
as reminders that these paths exist, in case the current setup stops being
enough.

## Documented Q&A from the project development

### 1. Full LocalStack emulation (Lambda + API Gateway)

Right now local dev runs `uvicorn --reload` directly against the FastAPI app
(`create_app()`), bypassing Mangum/Lambda/API Gateway entirely. LocalStack
only emulates the services the app *calls* at runtime (S3, SQS, DynamoDB) —
not the services it's *deployed into*.

LocalStack can also emulate Lambda + API Gateway, so the api container could
run through the exact same deployment topology as production instead of
short-circuiting it.

**Trade-off:** higher fidelity (tests the actual API Gateway → Lambda →
Mangum adapter locally) vs. losing hot reload — every code change would need
a zip rebuild + redeploy into LocalStack's fake Lambda before it's testable,
instead of an instant `--reload`.

### 2. `cdklocal` for the `init` service

`init-localstack.sh` hand-copies the DynamoDB table schema (PK/SK/GSI1) from
`infra/stacks/data_stack.py`. If the CDK stack changes and the script isn't
updated to match, they drift silently.

[`cdklocal`](https://github.com/localstack/aws-cdk-local) (npm package
`aws-cdk-local`) wraps the real `cdk` CLI and redirects its AWS calls to
LocalStack, so `cdklocal deploy` could provision the *same* CDK stack code
locally — no duplicated schema, single source of truth.

**Trade-off:** eliminates drift risk vs. a much slower/heavier `init` step —
full CloudFormation-style deploy (change sets, dependency ordering, stack
events) against LocalStack takes seconds-to-tens-of-seconds, vs. ~1s for a
plain `awslocal dynamodb create-table`. Also pulls in a second toolchain
(Node + `aws-cdk-local`) and a one-time `cdklocal bootstrap` step.
