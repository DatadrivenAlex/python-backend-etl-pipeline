"""JSON logs on stdout. Payloads stay out of the log line; ids and counts do not."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "event_fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    if getattr(root, "_etl_configured", False):
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    root._etl_configured = True  # type: ignore[attr-defined]


def log_event(logger: logging.Logger, message: str, **fields: object) -> None:
    logger.info(message, extra={"event_fields": fields})
