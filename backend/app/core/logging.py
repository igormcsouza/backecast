"""Logging configuration for the application.

This module sets up the logging configuration for the application
and exposes a preconfigured logger that emits JSON-formatted
log records to the standard output stream.

The JSON formatter produces a compact JSON object with the
following keys: timestamp, level, name, message, and optionally
exception and extra fields when present.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.core.settings import get_settings


class JsonFormatter(logging.Formatter):
    """Simple JSON formatter for logging.LogRecord objects."""

    def format(self, record: logging.LogRecord) -> str:
        record_dict = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            record_dict["exception"] = self.formatException(record.exc_info)

        # Include any extra attributes passed in the record
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "taskName",
            )
        }
        if extras:
            record_dict["extra"] = extras

        return json.dumps(record_dict, ensure_ascii=False)


settings = get_settings()

# Create and configure the module-level logger
logger = logging.getLogger("backecast")
logger.setLevel(logging.DEBUG if settings.stage == "dev" else logging.INFO)

# Avoid adding multiple handlers if this module is imported repeatedly
if not logger.handlers:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)


# Convenience dependency injection function to get a logger with a specific name
def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"backecast.{name}")
