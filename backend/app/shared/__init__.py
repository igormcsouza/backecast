"""Reusable code shared across domains: integration clients for
external services (DynamoDB, S3, SQS, AI providers) and cross-domain
contracts (e.g. RepositoryAbstract). Not wired onto the FastAPI `app`
itself — that's core/.
"""
