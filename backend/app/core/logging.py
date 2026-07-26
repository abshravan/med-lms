"""Structured logging with PII redaction.

Auth code logs a lot of near-miss detail (invalid token, wrong audience, revoked
session). None of it may carry credentials or personal data into the log sink, so
redaction is enforced by a processor rather than by reviewer discipline.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.types import EventDict, WrappedLogger

# Keys whose values are never safe to log. Matched case-insensitively on the
# whole key name.
REDACTED_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "token",
        "access_token",
        "refresh_token",
        "session_token",
        "authorization",
        "cookie",
        "set_cookie",
        "secret",
        "api_key",
        "email",
        "ip_address",
    }
)

REDACTED_PLACEHOLDER = "[redacted]"


def redact_sensitive(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Replace the value of any sensitive key with a placeholder."""
    for key in list(event_dict.keys()):
        if key.lower() in REDACTED_KEYS and event_dict[key] is not None:
            event_dict[key] = REDACTED_PLACEHOLDER
    return event_dict


def configure_logging(*, debug: bool = False, json_output: bool = True) -> None:
    """Configure structlog once, at application start."""
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    processors: list[Any] = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for a module."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
