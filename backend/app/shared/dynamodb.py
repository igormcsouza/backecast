"""Shared DynamoDB utilities.

Important to note that here we are using aioboto3, which is an
asynchronous version of boto3. This allows us to perform non-blocking
operations when interacting with DynamoDB, making our application more
efficient and responsive.

The DynamoDB resource is created once, in `lifespan`, and reused for the
app's whole lifetime — aioboto3's own docs call out that creating a new
session/resource per call is wasteful (it opens a fresh aiohttp connection
pool each time). `lifespan` is wired into `create_app()` in main.py, and
Mangum is told to actually run it (`lifespan="on"`) so a cold Lambda
container creates the resource once and reuses it across warm invocations.

Today the application is deployed into AWS Lambda, which is a serverless
compute service that runs code in response to events and automatically
manages the underlying compute resources. In this context, using
asynchronous operations does not actually improve performance, but if
the project grows to ECS in the future it will be a good practice to have
async code in place.
"""

from contextlib import asynccontextmanager

import aioboto3
from aiobotocore.config import AioConfig
from fastapi import FastAPI, Request

from app.core.settings import get_settings

session = aioboto3.Session()

# A held-open connection to a dead endpoint must fail fast, not hang until
# Lambda's own timeout kills the invocation — this bit us for real: after
# switching to a lifespan-scoped (reused) connection pool, a mid-life
# LocalStack restart made a request hang for 5+ seconds instead of failing
# instantly like the old per-request-connection code did.
CLIENT_CONFIG = AioConfig(
    connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    async with session.resource(
        "dynamodb",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        config=CLIENT_CONFIG,
    ) as dynamodb_resource:
        app.state.dynamodb_resource = dynamodb_resource
        yield


async def get_table(request: Request):
    settings = get_settings()
    return await request.app.state.dynamodb_resource.Table(settings.table_name)
