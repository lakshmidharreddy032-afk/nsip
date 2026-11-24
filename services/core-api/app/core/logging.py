"""structlog JSON logging with PII masking and secret redaction applied to every event."""
from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.ai.guards.pii import mask_obj

_SECRET_KEYS = re.compile(r"(password|secret|token|authorization|api[_-]?key|cookie)", re.I)


def _redact(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> Any:
    for k in list(event_dict):
        if _SECRET_KEYS.search(k):
            event_dict[k] = "[REDACTED]"
    return mask_obj(event_dict)


def configure_logging(level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "nsip"):
    return structlog.get_logger(name)
