"""Structured JSON logging bound to a per-request id. Logs carry route, status, elapsed
time, and safe service/stage fields only. Secrets (JWTs, operator/provider keys, DB URLs,
R2 credentials) and prompt content are never logged."""
from __future__ import annotations
import json
import logging
import sys
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "requestId": get_request_id(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def get_logger(name: str = "citycrawl_api") -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, message: str, **fields: object) -> None:
    logger.info(message, extra={"fields": fields})
