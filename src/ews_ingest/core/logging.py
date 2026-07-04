"""Structured (JSON) logging setup for fetch jobs."""

from __future__ import annotations

import json
import logging
from typing import override

__all__ = ["get_logger"]


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = {k: v for k, v in record.__dict__.items() if k not in _BASE_FIELDS}
        if extra:
            payload["extra"] = dict(extra)
        return json.dumps(payload, default=str)


_BASE_FIELDS = frozenset(
    {
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
        "message",
        "taskName",
    }
)


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger that writes JSON lines to stderr."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
